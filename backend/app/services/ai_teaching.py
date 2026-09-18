import json
import logging
import time
from pathlib import Path

import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from app.core.config import Settings
from app.models.explanation_attempt import ExplanationAttempt
from app.models.external_call_record import ExternalCallRecord
from app.models.question import Question
from app.models.session import Session
from app.models.support_event import SupportEvent
from app.repositories.sessions import SessionRepository, session_run_id
from app.rules.teaching_decision import TeachingDecision
from app.schemas.ai_evaluation import AIEvaluationOutput
from app.schemas.model_request_snapshot import (
    ModelRequestBlocks,
    ModelRequestMessage,
    ModelRequestPrivacy,
    ModelRequestSnapshot,
    ModelTransportSnapshot,
)
from app.schemas.teaching import InstructionFromRules, TeachingContext, TeachingOutput
from app.services.ai_evaluation import AIModelClient, AIModelResponse, AITransportError
from app.services.ai_reasoning import resolve_reasoning_params
from app.services.session_event_log import SessionEventLog

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "generate_teaching.md"
SHARED_SYSTEM_PATH = Path(__file__).resolve().parents[1] / "prompts" / "shared_system.md"
RESPONSE_GOALS = {
    "ASK_FOCUSED_QUESTION": "ASK_ONE_FOCUSED_QUESTION",
    "GIVE_HINT": "GIVE_ONE_LOCAL_HINT",
    "GIVE_CORRECTION": "CORRECT_IDENTIFIED_ERROR",
}
logger = logging.getLogger(__name__)


class AITeachingService:
    def __init__(
        self, database_session: DatabaseSession, settings: Settings, http_client: httpx.Client
    ) -> None:
        self.repository = SessionRepository(database_session)
        self.settings = settings
        self.client = AIModelClient(settings, http_client)

    def generate(
        self,
        *,
        question: Question,
        session: Session,
        attempt: ExplanationAttempt,
        evaluation: AIEvaluationOutput,
        decision: TeachingDecision,
    ) -> TeachingOutput | None:
        context = _build_context(
            self.repository.database_session,
            question=question,
            session=session,
            attempt=attempt,
            evaluation=evaluation,
            decision=decision,
        )
        validation_errors: list[str] = []
        previous_output: str | None = None
        external_attempt_number = 0
        run_id = session_run_id(session.id, attempt.id)
        event_log = SessionEventLog(self.repository.database_session)

        for schema_attempt in range(self.settings.ai_schema_max_retries + 1):
            request = _render_prompt(
                context,
                validation_errors=validation_errors,
                previous_output=previous_output,
                model=self.settings.ai_model,
                prompt_version=self.settings.prompt_version,
                reasoning_effort=self.settings.ai_reasoning_effort,
            )
            from app.services.context_runtime import prepare_request

            prepare_request(request, self.repository.database_session, session,
                            exclude_attempt_id=attempt.id)
            request.transport.extra_body["max_tokens"] = self.settings.ai_max_output_tokens
            if schema_attempt == 0:
                event_log.append_contexts(
                    session_id=session.id,
                    run_id=run_id,
                    request=request,
                    question_source=f"question:{question.id}",
                    parent_event_id=event_log.latest_event_id(session.id, run_id),
                )
            model_response, external_call, external_attempt_number, requested_event_id = (
                self._call_with_transport_retries(
                    session=session,
                    request=request,
                    external_attempt_number=external_attempt_number,
                    run_id=run_id,
                    exclude_attempt_id=attempt.id,
                )
            )
            if model_response is None:
                return None
            if external_call is None:
                raise RuntimeError("AI 教学传输成功后缺少外部调用记录")

            output, validation_errors = _parse_and_validate(
                model_response.content, context=context
            )
            if validation_errors:
                previous_output = model_response.content
                self.repository.record_external_call_validation(
                    record=external_call,
                    validation_status="INVALID",
                    validation_errors=validation_errors,
                )
                event_log.append_model_responded(
                    session_id=session.id,
                    run_id=run_id,
                    response_content=model_response.content,
                    validation="invalid",
                    duration_ms=model_response.duration_ms,
                    parent_event_id=requested_event_id,
                    raw_response=model_response.raw_response,
                )
                if schema_attempt == self.settings.ai_schema_max_retries:
                    return None
                continue

            if output is None:
                raise RuntimeError("AI 教学校验完成后缺少教学结果")
            self.repository.record_external_call_validation(
                record=external_call,
                validation_status="VALID",
                validation_errors=[],
            )
            event_log.append_model_responded(
                session_id=session.id,
                run_id=run_id,
                response_content=model_response.content,
                validation="valid",
                duration_ms=model_response.duration_ms,
                parent_event_id=requested_event_id,
                raw_response=model_response.raw_response,
            )
            return output
        raise RuntimeError("AI 教学结构重试循环未产生结果")

    def _call_with_transport_retries(
        self,
        *,
        session: Session,
        request: ModelRequestSnapshot,
        external_attempt_number: int,
        run_id: str,
        exclude_attempt_id: int,
    ) -> tuple[AIModelResponse | None, ExternalCallRecord | None, int, str | None]:
        event_log = SessionEventLog(self.repository.database_session)
        for transport_attempt in range(self.settings.ai_transport_max_retries + 1):
            current_attempt_number = external_attempt_number + 1
            requested_event = event_log.append_model_requested(
                session_id=session.id,
                run_id=run_id,
                request=request,
                provider=self.settings.ai_provider,
                parent_event_id=event_log.latest_event_id(session.id, run_id),
            )
            try:
                from app.services.context_runtime import evaluate_request

                model_response, response_event_id = evaluate_request(
                    self.client, request, self.repository.database_session, session,
                    requested_event.event_id, run_id,
                    exclude_attempt_id=exclude_attempt_id,
                )
            except AITransportError as error:
                self.repository.record_external_call(
                    session=session,
                    call_type="AI_TEACHING",
                    attempt_number=current_attempt_number,
                    transport_status="ERROR",
                    duration_ms=error.duration_ms,
                    provider=self.settings.ai_provider,
                    model=self.settings.ai_model,
                    error_type=error.error_type,
                    error_message=str(error),
                    raw_response=error.raw_response,
                    request_snapshot=request,
                )
                event_log.append_model_failed(
                    session_id=session.id,
                    run_id=run_id,
                    error_type=error.error_type,
                    message=str(error),
                    duration_ms=error.duration_ms,
                    parent_event_id=requested_event.event_id,
                )
                if transport_attempt == self.settings.ai_transport_max_retries:
                    return None, None, current_attempt_number, requested_event.event_id
                time.sleep(self.settings.ai_retry_backoff_seconds[transport_attempt])
                external_attempt_number = current_attempt_number
                continue
            external_call = self.repository.record_external_call(
                session=session,
                call_type="AI_TEACHING",
                attempt_number=current_attempt_number,
                transport_status="SUCCESS",
                duration_ms=model_response.duration_ms,
                provider=self.settings.ai_provider,
                model=self.settings.ai_model,
                raw_response=model_response.raw_response,
                request_snapshot=request,
            )
            logger.info(
                "AI 教学调用完成",
                extra={
                    "eventName": "ai.call.completed",
                    "purpose": request.purpose,
                    "model": self.settings.ai_model,
                    "durationMs": model_response.duration_ms,
                },
            )
            return model_response, external_call, current_attempt_number, response_event_id
        raise RuntimeError("AI 教学传输重试循环未产生结果")


def _build_context(
    database_session: DatabaseSession,
    *,
    question: Question,
    session: Session,
    attempt: ExplanationAttempt,
    evaluation: AIEvaluationOutput,
    decision: TeachingDecision,
) -> TeachingContext:
    if not decision.should_generate or decision.allowed_action is None:
        raise ValueError("当前确定性决策不允许调用教学模型")
    supports = list(
        database_session.scalars(
            select(SupportEvent)
            .where(SupportEvent.session_id == session.id, SupportEvent.status == "VALID")
            .order_by(SupportEvent.id.desc())
            .limit(9)
        )
    )
    history = [
        {
            "supportType": item.support_type,
            "content": item.content,
            "questions": item.guided_questions or [],
            "answers": item.guided_answers or [],
            "followUpContent": item.follow_up_content,
        }
        for item in reversed(supports)
    ]
    return TeachingContext(
        question={
            "questionContent": question.question_content,
            "standardAnswer": question.standard_answer,
            "rubricPoints": question.rubric_points or [],
            "commonErrors": question.common_errors or [],
            "alternativeSolutions": question.alternative_solutions or [],
            "layeredHints": question.layered_hints or [],
            "guidedQuestions": question.guided_questions or [],
            "fullSolution": question.full_solution,
        },
        current_student_text=attempt.confirmed_text,
        latest_evaluation=evaluation,
        teaching_history=history,
        instruction_from_rules=InstructionFromRules(
            allowed_action=decision.allowed_action,
            do_not_repeat=[item.content for item in supports],
            do_not_reveal=[
                "DO_NOT_REVEAL_FULL_SOLUTION",
                "DO_NOT_QUOTE_STANDARD_ANSWER",
                "DO_NOT_ANSWER_FUTURE_RUBRIC_POINTS",
            ],
            response_goal=RESPONSE_GOALS[decision.allowed_action],
        ),
    )


def _render_prompt(
    context: TeachingContext,
    *,
    validation_errors: list[str],
    previous_output: str | None,
    model: str,
    prompt_version: str,
    reasoning_effort: str | None,
) -> ModelRequestSnapshot:
    shared_system = SHARED_SYSTEM_PATH.read_text(encoding="utf-8")
    template = PROMPT_PATH.read_text(encoding="utf-8")
    schema = TeachingOutput.model_json_schema(by_alias=True)
    # 五层消息
    # messages[0] system：全局共享前缀
    # messages[1] user：会话级稳定上下文（题目数据）
    question_context = dict(context.question)
    question_message = {k: v for k, v in question_context.items() if k != "outputSchema"}
    # messages[2] user：截至当前任务前的共享历史（教学历史）
    shared_history = {"teachingHistory": context.teaching_history}
    # messages[3] user：taskType 固定指令 + JSON Schema
    task_prompt = template.replace(
        "{{JSON_SCHEMA}}", json.dumps(schema, ensure_ascii=False)
    )
    # messages[4] user：本轮任务数据
    current_data: dict[str, object] = {
        "currentStudentText": context.current_student_text,
        "latestEvaluation": context.latest_evaluation.model_dump(mode="json", by_alias=True),
        "instructionFromRules": context.instruction_from_rules.model_dump(
            mode="json", by_alias=True
        ),
    }
    if validation_errors:
        current_data["previousOutput"] = previous_output
        current_data["validationErrors"] = validation_errors
    elif previous_output is not None:
        current_data["previousOutput"] = previous_output
        current_data["validationErrors"] = []
    extra_body = resolve_reasoning_params(model, reasoning_effort)
    return ModelRequestSnapshot(
        schema_version="1.1",
        purpose="AI_TEACHING",
        prompt_version=prompt_version,
        blocks=ModelRequestBlocks(
            system_instructions=shared_system,
            task_instructions=task_prompt,
            question_context=question_context,
            session_context={
                "taskType": context.task_type,
                "latestEvaluation": context.latest_evaluation.model_dump(
                    mode="json", by_alias=True
                ),
                "teachingHistory": context.teaching_history,
                "instructionFromRules": context.instruction_from_rules.model_dump(
                    mode="json", by_alias=True
                ),
            },
            user_input={"currentStudentText": context.current_student_text},
            retry_context={
                "validationErrors": validation_errors,
                "previousOutput": previous_output,
            },
        ),
        transport=ModelTransportSnapshot(
            model=model,
            messages=[
                ModelRequestMessage(role="system", content=shared_system),
                ModelRequestMessage(
                    role="user",
                    content=json.dumps(question_message, ensure_ascii=False),
                ),
                ModelRequestMessage(
                    role="user",
                    content=json.dumps(shared_history, ensure_ascii=False),
                ),
                ModelRequestMessage(role="user", content=task_prompt),
                ModelRequestMessage(
                    role="user",
                    content=json.dumps(current_data, ensure_ascii=False),
                ),
            ],
            response_format={"type": "json_object"},
            reasoning_effort=reasoning_effort,
            extra_body=extra_body,
        ),
        privacy=ModelRequestPrivacy(
            contains_student_content=True,
            contains_answer_material=True,
            contains_memory=False,
        ),
    )


def _parse_and_validate(
    content: str, *, context: TeachingContext
) -> tuple[TeachingOutput | None, list[str]]:
    try:
        output = TeachingOutput.model_validate_json(content)
    except ValidationError as error:
        return None, [entry["msg"] for entry in error.errors()]
    errors: list[str] = []
    action = context.instruction_from_rules.allowed_action
    expected_count = 1 if action == "ASK_FOCUSED_QUESTION" else 0
    if len(output.questions) != expected_count:
        errors.append(f"{action} 要求 questions 数量为 {expected_count}")

    combined_output = "\n".join(
        [output.content, *(question.question for question in output.questions)]
    )
    full_solution = context.question.get("fullSolution")
    standard_answer = context.question.get("standardAnswer")
    if isinstance(full_solution, str) and full_solution and full_solution in combined_output:
        errors.append("教学输出不得直接包含完整解析")
    if isinstance(standard_answer, str) and standard_answer and standard_answer in combined_output:
        errors.append("教学输出不得直接包含标准答案")
    normalized_content = _normalize(output.content)
    if normalized_content in {
        _normalize(item) for item in context.instruction_from_rules.do_not_repeat
    }:
        errors.append("教学输出不得完全重复已发送支持")
    return output, errors


def _normalize(value: str) -> str:
    return " ".join(value.split())
