"""对话后核验的 AI 能力层：生成核验问题、评价学生回答。

本模块只产出契约允许的问题与回答评价。是否进入核验、问题数量上限之外的
状态转换、支持计数和最终状态由规则层决定。
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import ValidationError
from sqlalchemy.orm import Session as DatabaseSession

from app.core.config import Settings
from app.models.explanation_attempt import ExplanationAttempt
from app.models.external_call_record import ExternalCallRecord
from app.models.question import Question as QuestionRecord
from app.models.session import Session
from app.repositories.sessions import SessionRepository
from app.schemas.ai_evaluation import AIEvaluationOutput
from app.schemas.mastery_check import (
    MasteryCheckAnswer,
    MasteryCheckAssessmentOutput,
    MasteryCheckQuestionsOutput,
    validate_mastery_check_assessment,
    validate_mastery_check_questions,
)
from app.schemas.model_request_snapshot import (
    ModelRequestBlocks,
    ModelRequestMessage,
    ModelRequestPrivacy,
    ModelRequestSnapshot,
    ModelTransportSnapshot,
)
from app.services.ai_evaluation import AIModelClient, AIModelResponse, AITransportError
from app.services.ai_reasoning import resolve_reasoning_params
from app.services.session_event_log import SessionEventLog

SHARED_SYSTEM_PATH = Path(__file__).resolve().parents[1] / "prompts" / "shared_system.md"
GENERATION_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "generate_mastery_check.md"
)
ASSESSMENT_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "evaluate_mastery_check.md"
)
OutputType = TypeVar("OutputType", MasteryCheckQuestionsOutput, MasteryCheckAssessmentOutput)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MasteryCheckEvidence:
    """核验问题生成的证据集合。

    `main_reason` 只提供问题方向，问题正文必须落在 `judge_reason`、
    `student_text` 或历史事件的具体内容上。
    """

    evaluation_id: int
    main_reason: str
    judge_reason: str
    student_text: str


@dataclass(frozen=True)
class MasteryCheckQuestionInput:
    """回答评价需要的问题正文与证据引用。"""

    question_id: str
    question: str
    evidence_refs: list[dict[str, object]]


class AIMasteryCheckService:
    def __init__(
        self, database_session: DatabaseSession, settings: Settings, http_client: httpx.Client
    ) -> None:
        self.repository = SessionRepository(database_session)
        self.settings = settings
        self.client = AIModelClient(settings, http_client)

    def generate_questions(
        self,
        *,
        question: QuestionRecord,
        session: Session,
        attempt: ExplanationAttempt,
        evaluation_id: int,
    ) -> MasteryCheckQuestionsOutput | None:
        evidence = self._build_evidence(
            session=session, attempt=attempt, evaluation_id=evaluation_id
        )
        if evidence is None:
            return None
        progress_context = self._build_progress_context(session)
        return self._generate(
            session=session,
            request_builder=lambda validation_errors: _render_generation_prompt(
                question=question,
                session=session,
                evidence=evidence,
                validation_errors=validation_errors,
                model=self.settings.ai_model,
                prompt_version=self.settings.prompt_version,
                reasoning_effort=self.settings.ai_reasoning_effort,
                progress_context=progress_context,
            ),
            output_type=MasteryCheckQuestionsOutput,
            validator=validate_mastery_check_questions,
            purpose="AI_MASTERY_CHECK",
        )

    def evaluate_answers(
        self,
        *,
        question: QuestionRecord,
        session: Session,
        questions: list[MasteryCheckQuestionInput],
        answers: list[MasteryCheckAnswer],
    ) -> MasteryCheckAssessmentOutput | None:
        if not questions:
            raise ValueError("核验回答评价缺少已发送问题")
        question_ids = [item.question_id for item in questions]
        progress_context = self._build_progress_context(session)
        return self._generate(
            session=session,
            request_builder=lambda validation_errors: _render_assessment_prompt(
                question=question,
                session=session,
                questions=questions,
                answers=answers,
                validation_errors=validation_errors,
                model=self.settings.ai_model,
                prompt_version=self.settings.prompt_version,
                reasoning_effort=self.settings.ai_reasoning_effort,
                progress_context=progress_context,
            ),
            output_type=MasteryCheckAssessmentOutput,
            validator=lambda output: validate_mastery_check_assessment(output, question_ids),
            purpose="MASTERY_CHECK_ASSESSMENT",
        )

    def _build_evidence(
        self,
        *,
        session: Session,
        attempt: ExplanationAttempt,
        evaluation_id: int,
    ) -> MasteryCheckEvidence | None:
        """读取最近一次有效评价的结构化输出作为问题生成证据。

        评价的 mainReason、otherReasons 和 judgeReason 保存在模型响应事件中，
        这里集中解析一次，避免调用点各自解析原始事件 JSON。
        """
        evaluation = self.repository.get_latest_valid_evaluation(session.id)
        if evaluation is None or evaluation.id != evaluation_id:
            return None
        if evaluation.attempt_id != attempt.id:
            return None
        output = self._latest_evaluation_output(session, attempt.id)
        if output is None:
            return None
        if output.main_reason is None or output.judge_reason is None:
            return None
        return MasteryCheckEvidence(
            evaluation_id=evaluation.id,
            main_reason=output.main_reason,
            judge_reason=output.judge_reason,
            student_text=attempt.confirmed_text or "",
        )

    def _latest_evaluation_output(
        self, session: Session, attempt_id: int
    ) -> AIEvaluationOutput | None:
        events = SessionEventLog(self.repository.database_session).event_store.list_events(
            session.id
        )
        run_id = f"run_session_{session.id}_attempt_{attempt_id}"
        for event in reversed(events):
            if event.run_id != run_id or event.event_type != "model.responded":
                continue
            if event.data.get("validation") != "valid":
                continue
            output = event.data.get("output")
            if not isinstance(output, dict):
                return None
            try:
                return AIEvaluationOutput.model_validate(output)
            except ValidationError:
                return None
        return None

    def _build_progress_context(self, session: Session) -> dict[str, object]:
        from app.services.context_history import build_shared_history

        return build_shared_history(self.repository.database_session, session)

    def _generate(
        self,
        *,
        session: Session,
        request_builder: Callable[[list[str]], ModelRequestSnapshot],
        output_type: type[OutputType],
        validator: Callable[[OutputType], list[str]],
        purpose: str,
    ) -> OutputType | None:
        validation_errors: list[str] = []
        external_attempt_number = 0
        run_id = self._run_id(session, purpose)
        event_log = SessionEventLog(self.repository.database_session)
        for schema_attempt in range(self.settings.ai_schema_max_retries + 1):
            request = request_builder(validation_errors)
            from app.services.context_runtime import prepare_request

            prepare_request(request, self.repository.database_session, session)
            request.transport.extra_body["max_tokens"] = self.settings.ai_max_output_tokens
            if schema_attempt == 0:
                event_log.append_contexts(
                    session_id=session.id,
                    run_id=run_id,
                    request=request,
                    question_source="question",
                    parent_event_id=event_log.latest_event_id(session.id, run_id),
                )
            model_response, external_call, external_attempt_number, requested_event_id = (
                self._call_with_transport_retries(
                    session=session,
                    request=request,
                    external_attempt_number=external_attempt_number,
                    run_id=run_id,
                )
            )
            if model_response is None:
                self.repository.request_human_review(
                    session=session,
                    need_human_reason="AI 核验服务在配置的重试次数内未成功响应",
                    trigger_type="AI_MASTERY_CHECK_TRANSPORT_RETRY_EXHAUSTED",
                    run_id=run_id,
                )
                return None
            if external_call is None:
                raise RuntimeError("AI 核验传输成功后缺少外部调用记录")
            try:
                output = output_type.model_validate_json(model_response.content)
                validation_errors = validator(output)
                if validation_errors:
                    raise ValueError("；".join(validation_errors))
            except (ValidationError, ValueError) as error:
                validation_errors = (
                    [entry["msg"] for entry in error.errors()]
                    if isinstance(error, ValidationError)
                    else [str(error)]
                )
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
                logger.log(
                    logging.ERROR
                    if schema_attempt == self.settings.ai_schema_max_retries
                    else logging.WARNING,
                    "AI 核验输出校验失败",
                    extra={
                        "eventName": "ai.output.validation_failed",
                        "purpose": purpose,
                        "model": self.settings.ai_model,
                        "durationMs": model_response.duration_ms,
                        "errorType": "AI_SCHEMA_ERROR",
                    },
                )
                if schema_attempt == self.settings.ai_schema_max_retries:
                    self.repository.request_human_review(
                        session=session,
                        need_human_reason="AI 核验在配置的重试次数内仍不合法："
                        + "；".join(validation_errors),
                        trigger_type="AI_MASTERY_CHECK_SCHEMA_RETRY_EXHAUSTED",
                        run_id=run_id,
                    )
                    return None
                continue
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
            logger.info(
                "AI 核验输出校验通过",
                extra={
                    "eventName": "ai.output.validated",
                    "purpose": purpose,
                    "model": self.settings.ai_model,
                    "durationMs": model_response.duration_ms,
                },
            )
            return output
        raise RuntimeError("AI 核验结构重试循环未产生结果")

    def _call_with_transport_retries(
        self,
        *,
        session: Session,
        request: ModelRequestSnapshot,
        external_attempt_number: int,
        run_id: str,
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
                )
            except AITransportError as error:
                self.repository.record_external_call(
                    session=session,
                    call_type=request.purpose,
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
                logger.log(
                    logging.ERROR
                    if transport_attempt == self.settings.ai_transport_max_retries
                    else logging.WARNING,
                    "AI 核验调用失败",
                    extra={
                        "eventName": "ai.call.failed",
                        "purpose": request.purpose,
                        "model": self.settings.ai_model,
                        "durationMs": error.duration_ms,
                        "errorType": error.error_type,
                    },
                )
                if transport_attempt == self.settings.ai_transport_max_retries:
                    return None, None, current_attempt_number, requested_event.event_id
                time.sleep(self.settings.ai_retry_backoff_seconds[transport_attempt])
                external_attempt_number = current_attempt_number
                continue
            external_call = self.repository.record_external_call(
                session=session,
                call_type=request.purpose,
                attempt_number=current_attempt_number,
                transport_status="SUCCESS",
                duration_ms=model_response.duration_ms,
                provider=self.settings.ai_provider,
                model=self.settings.ai_model,
                raw_response=model_response.raw_response,
                request_snapshot=request,
            )
            logger.info(
                "AI 核验调用完成",
                extra={
                    "eventName": "ai.call.completed",
                    "purpose": request.purpose,
                    "model": self.settings.ai_model,
                    "durationMs": model_response.duration_ms,
                },
            )
            return model_response, external_call, current_attempt_number, response_event_id
        raise RuntimeError("AI 核验传输重试循环未产生结果")

    @staticmethod
    def _run_id(session: Session, purpose: str) -> str:
        return f"run_session_{session.id}_mastery_check_{purpose}_{session.version}"


def _render_generation_prompt(
    *,
    question: QuestionRecord,
    session: Session,
    evidence: MasteryCheckEvidence,
    validation_errors: list[str],
    model: str,
    prompt_version: str,
    reasoning_effort: str | None = None,
    progress_context: dict[str, object] | None = None,
) -> ModelRequestSnapshot:
    template = GENERATION_PROMPT_PATH.read_text(encoding="utf-8")
    user_input: dict[str, object] = {
        "mainReason": evidence.main_reason,
        "judgeReason": evidence.judge_reason,
        "studentText": evidence.student_text,
    }
    return _model_request(
        purpose="AI_MASTERY_CHECK",
        prompt_version=prompt_version,
        task_instructions=template,
        question=question,
        session=session,
        user_input=user_input,
        validation_errors=validation_errors,
        model=model,
        reasoning_effort=reasoning_effort,
        progress_context=progress_context,
    )


def _render_assessment_prompt(
    *,
    question: QuestionRecord,
    session: Session,
    questions: list[MasteryCheckQuestionInput],
    answers: list[MasteryCheckAnswer],
    validation_errors: list[str],
    model: str,
    prompt_version: str,
    reasoning_effort: str | None = None,
    progress_context: dict[str, object] | None = None,
) -> ModelRequestSnapshot:
    template = ASSESSMENT_PROMPT_PATH.read_text(encoding="utf-8")
    user_input: dict[str, object] = {
        "questions": [
            {
                "id": item.question_id,
                "question": item.question,
                "evidenceRefs": item.evidence_refs,
            }
            for item in questions
        ],
        "answers": [answer.model_dump() for answer in answers],
    }
    return _model_request(
        purpose="MASTERY_CHECK_ASSESSMENT",
        prompt_version=prompt_version,
        task_instructions=template,
        question=question,
        session=session,
        user_input=user_input,
        validation_errors=validation_errors,
        model=model,
        reasoning_effort=reasoning_effort,
        progress_context=progress_context,
    )


def _question_context(question: QuestionRecord) -> dict[str, object]:
    return {
        "questionContent": question.question_content,
        "standardAnswer": question.standard_answer,
        "rubricPoints": question.rubric_points,
        "commonErrors": question.common_errors,
        "alternativeSolutions": question.alternative_solutions,
        "layeredHints": question.layered_hints,
        "guidedQuestions": question.guided_questions,
        "fullSolution": question.full_solution,
    }


def _model_request(
    *,
    purpose: str,
    prompt_version: str,
    task_instructions: str,
    question: QuestionRecord,
    session: Session,
    user_input: dict[str, object],
    validation_errors: list[str],
    model: str,
    reasoning_effort: str | None = None,
    progress_context: dict[str, object] | None = None,
) -> ModelRequestSnapshot:
    shared_system = SHARED_SYSTEM_PATH.read_text(encoding="utf-8")
    question_context = _question_context(question)
    # 核验请求不携带 round、supportCountRound 等业务计数：这些值由规则层控制，
    # 模型既不需要也不允许据此改变流程。
    session_context: dict[str, object] = {"taskType": "MASTERY_CHECK"}
    shared_history = progress_context or {"events": []}
    current_data = dict(user_input)
    if validation_errors:
        current_data["validationErrors"] = validation_errors
    extra_body = resolve_reasoning_params(model, reasoning_effort)
    return ModelRequestSnapshot(
        schema_version="1.1",
        purpose=purpose,
        prompt_version=prompt_version,
        blocks=ModelRequestBlocks(
            system_instructions=shared_system,
            task_instructions=task_instructions,
            question_context=question_context,
            session_context=session_context,
            user_input=user_input,
            retry_context={"validationErrors": validation_errors},
        ),
        transport=ModelTransportSnapshot(
            model=model,
            messages=[
                ModelRequestMessage(role="system", content=shared_system),
                ModelRequestMessage(
                    role="user",
                    content=json.dumps(question_context, ensure_ascii=False),
                ),
                ModelRequestMessage(
                    role="user", content=json.dumps(shared_history, ensure_ascii=False)
                ),
                ModelRequestMessage(role="user", content=task_instructions),
                ModelRequestMessage(
                    role="user", content=json.dumps(current_data, ensure_ascii=False)
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
