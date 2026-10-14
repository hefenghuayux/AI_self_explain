import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from app.models.explanation_attempt import ExplanationAttempt
from app.models.first_explanation_grading import FirstExplanationGrading
from app.models.question import Question
from app.models.session import Session
from app.repositories.sessions import SessionRepository
from app.rules.first_explanation_grading import (
    FIRST_EXPLANATION_GRADING_VERSION,
    calculate_total_score,
)
from app.schemas.first_explanation_grading import FirstExplanationGradingOutput
from app.schemas.model_request_snapshot import (
    ModelRequestBlocks,
    ModelRequestMessage,
    ModelRequestPrivacy,
    ModelRequestSnapshot,
    ModelTransportSnapshot,
)
from app.services.ai_evaluation import AIModelClient
from app.services.ai_run import AIRunCancelled, bind_run, finish_run
from app.services.ai_stream import current_stream, stream_failed, stream_validated

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "first_explanation_grading.md"


def to_grading_response(record: FirstExplanationGrading):
    from app.schemas.first_explanation_grading import FirstExplanationGradingResponse

    report = record.report
    if report is not None:
        report = dict(report)
        report["totalScore"] = record.total_score
    return FirstExplanationGradingResponse.model_validate(
        {
            "id": record.id,
            "attemptId": record.attempt_id,
            "status": record.status,
            "evaluationStatus": record.evaluation_status,
            "report": report,
            "evaluationError": record.evaluation_error,
            "errorMessage": record.error_message,
            "acknowledgedAt": record.acknowledged_at,
            "standardVersion": record.standard_version,
            "createdAt": record.created_at,
        }
    )


def create_grading_record(
    db, session: Session, attempt: ExplanationAttempt
) -> FirstExplanationGrading:
    record = FirstExplanationGrading(
        session_id=session.id,
        attempt_id=attempt.id,
        status="PENDING",
        evaluation_status="PENDING",
        standard_version=FIRST_EXPLANATION_GRADING_VERSION,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _build_request(
    question: Question, attempt: ExplanationAttempt, settings
) -> ModelRequestSnapshot:
    student_steps = attempt.student_explanation or {
        "stepContent": attempt.confirmed_text or "",
        "explainTranscript": "",
    }
    question_context = {
        "questionContent": question.question_content,
        "standardAnswer": question.standard_answer,
        "rubricPoints": question.rubric_points or [],
        "alternativeSolutions": question.alternative_solutions or [],
    }
    content = json.dumps({"studentSteps": [student_steps]}, ensure_ascii=False)
    task = PROMPT_PATH.read_text(encoding="utf-8")
    # 传输层使用 JSON object 模式，字段约束与本地校验共用同一份 Schema。
    output_schema = FirstExplanationGradingOutput.model_json_schema(by_alias=True)
    system_instructions = (
        "只返回符合以下 JSON Schema 的合法 JSON 对象，所有必填字段都必须提供。\n"
        + json.dumps(output_schema, ensure_ascii=False)
    )
    messages = [
        ModelRequestMessage(role="system", content=system_instructions),
        ModelRequestMessage(role="user", content=json.dumps(question_context, ensure_ascii=False)),
        ModelRequestMessage(role="user", content=task),
        ModelRequestMessage(role="user", content=content),
    ]
    return ModelRequestSnapshot(
        schemaVersion="1.1",
        purpose="FIRST_EXPLANATION_GRADING",
        promptVersion=FIRST_EXPLANATION_GRADING_VERSION,
        blocks=ModelRequestBlocks(
            systemInstructions=system_instructions,
            questionContext=question_context,
            sessionContext={"attemptId": attempt.id},
            taskInstructions=task,
            userInput={"studentSteps": [student_steps]},
            retryContext={"validationErrors": []},
        ),
        transport=ModelTransportSnapshot(
            model=settings.ai_model,
            messages=messages,
            response_format={"type": "json_object"},
            reasoning_effort=settings.ai_reasoning_effort,
            extra_body={"max_tokens": settings.ai_max_output_tokens,
                        **({"stream": True, "stream_options": {"include_usage": True}}
                           if current_stream.get() else {})},
        ),
        privacy=ModelRequestPrivacy(
            containsStudentContent=True, containsAnswerMaterial=True, containsMemory=False
        ),
    )


def run_grading(
    *, db, record: FirstExplanationGrading, session: Session, attempt: ExplanationAttempt,
    question: Question, settings, http_client,
) -> None:
    record.status = "RUNNING"
    db.commit()
    try:
        response = AIModelClient(settings, http_client).evaluate(
            _build_request(question, attempt, settings)
        )
        payload = json.loads(response.content)
        report = FirstExplanationGradingOutput.model_validate(payload)
        total = calculate_total_score(report.correctness_score, report.completeness_score)
        saved = report.model_dump(mode="json", by_alias=True)
        saved["totalScore"] = total
        record.report = saved
        record.correctness_score = report.correctness_score
        record.completeness_score = report.completeness_score
        record.total_score = total
        record.status = "SUCCEEDED"
        record.error_message = None
        db.commit()
        stream_validated("FIRST_EXPLANATION_GRADING")
        context = current_stream.get()
        if context is not None:
            context.registry.update_result(
                context.run_id,
                {"grading": to_grading_response(record).model_dump(mode="json", by_alias=True)},
            )
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
        stream_failed("FIRST_EXPLANATION_GRADING")
        record.status = "FAILED"
        record.error_message = f"评分输出校验失败：{error}"
        db.commit()
    except Exception as error:
        stream_failed("FIRST_EXPLANATION_GRADING")
        if isinstance(error, AIRunCancelled):
            db.rollback()
            return
        logger.exception("首次自讲评分失败 grading=%s", record.id)
        record.status = "FAILED"
        record.error_message = f"评分服务失败：{error}"
        db.commit()


def run_parallel_tasks(
    *, settings, http_client, database_session_factory, session_id: int, attempt_id: int,
    grading_id: int, teacher_speech_service=None, prewarm_speech: bool = False,
    run_id: str | None = None, runtime=None,
):
    stream_context = current_stream.get()
    from app.services.context_runtime import current_context

    request_context = current_context.get()

    def run_evaluation() -> None:
        from app.api.sessions import evaluate_explanation_attempt

        with database_session_factory() as db:
            current_stream.set(stream_context)
            current_context.set(request_context)
            if run_id is not None:
                bind_run(db, session_id, run_id, runtime)
            session = db.get(Session, session_id)
            attempt = db.get(ExplanationAttempt, attempt_id)
            if session is None or attempt is None:
                return
            request = SimpleNamespace(
                headers={"X-Teacher-Speech-Prewarm": "true"} if prewarm_speech else {},
                app=SimpleNamespace(
                    state=SimpleNamespace(
                        settings=settings, ai_http_client=http_client,
                        teacher_speech_service=teacher_speech_service,
                    )
                )
            )
            try:
                evaluate_explanation_attempt(
                    repository=SessionRepository(db), session=session, attempt=attempt,
                    database_session=db, request=request,
                )
            except AIRunCancelled:
                db.rollback()
                return
            except Exception:
                logger.exception("后台自讲评价失败 session=%s", session_id)
                grading_db = database_session_factory()
                try:
                    if run_id is not None:
                        bind_run(grading_db, session_id, run_id, runtime)
                    grading_record = grading_db.get(FirstExplanationGrading, grading_id)
                    if grading_record is not None:
                        grading_record.evaluation_status = "FAILED"
                        grading_record.evaluation_error = "自讲评价服务失败，请稍后重试。"
                        grading_db.commit()
                except AIRunCancelled:
                    grading_db.rollback()
                finally:
                    grading_db.close()
                if session.flow_stage == "AI_EVALUATING":
                    SessionRepository(db).record_ai_service_failure(
                        session=session, flow_stage="CAPTURING_INPUT",
                        trigger_type="AI_EVALUATION_BACKGROUND_FAILED",
                        related_attempt_id=attempt.id,
                        run_id=f"session:{session.id}:attempt:{attempt.id}",
                    )
            else:
                grading_db = database_session_factory()
                try:
                    if run_id is not None:
                        bind_run(grading_db, session_id, run_id, runtime)
                    grading_record = grading_db.get(FirstExplanationGrading, grading_id)
                    if grading_record is not None:
                        grading_record.evaluation_status = "SUCCEEDED"
                        grading_record.evaluation_error = None
                        grading_db.commit()
                except AIRunCancelled:
                    grading_db.rollback()
                finally:
                    grading_db.close()

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="first-explanation") as executor:
        futures = [
            executor.submit(run_evaluation),
            executor.submit(
                run_grading_only,
                settings=settings,
                http_client=http_client,
                database_session_factory=database_session_factory,
                session_id=session_id,
                attempt_id=attempt_id,
                grading_id=grading_id,
                run_id=run_id,
                runtime=runtime,
                finish_on_completion=False,
                stream_context=stream_context,
            ),
        ]
        for future in futures:
            future.result()
    if run_id is not None and stream_context is None:
        with database_session_factory() as db:
            finish_run(db, session_id, run_id, runtime)


def run_grading_only(
    *, settings, http_client, database_session_factory, session_id: int, attempt_id: int,
    grading_id: int, run_id: str | None = None, runtime=None,
    finish_on_completion: bool = True,
    stream_context=None,
) -> None:
    if stream_context is not None:
        current_stream.set(stream_context)
    with database_session_factory() as db:
        if run_id is not None:
            bind_run(db, session_id, run_id, runtime)
        record = db.get(FirstExplanationGrading, grading_id)
        session = db.get(Session, session_id)
        attempt = db.get(ExplanationAttempt, attempt_id)
        question = None if session is None else db.get(Question, session.question_id)
        if record is None or session is None or attempt is None or question is None:
            return
        run_grading(
            db=db,
            record=record,
            session=session,
            attempt=attempt,
            question=question,
            settings=settings,
            http_client=http_client,
        )
    if run_id is not None and finish_on_completion and current_stream.get() is None:
        with database_session_factory() as db:
            finish_run(db, session_id, run_id, runtime)
