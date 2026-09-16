import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import ValidationError
from sqlalchemy.orm import Session as DatabaseSession

from app.core.config import Settings
from app.models.external_call_record import ExternalCallRecord
from app.models.question import Question
from app.models.session import Session
from app.models.support_event import SupportEvent
from app.repositories.sessions import SessionRepository
from app.schemas.model_request_snapshot import (
    ModelRequestBlocks,
    ModelRequestMessage,
    ModelRequestPrivacy,
    ModelRequestSnapshot,
    ModelTransportSnapshot,
)
from app.schemas.support import (
    GuidedAnswer,
    GuidedAnswerAssessmentOutput,
    SupportRequestOutput,
)
from app.services.ai_evaluation import AIModelClient, AIModelResponse, AITransportError
from app.services.ai_reasoning import resolve_reasoning_params
from app.services.session_event_log import SessionEventLog

SUPPORT_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "generate_support.md"
ASSESSMENT_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "assess_guided_answers.md"
)
OutputType = TypeVar("OutputType", SupportRequestOutput, GuidedAnswerAssessmentOutput)
logger = logging.getLogger(__name__)


class AISupportService:
    def __init__(
        self, database_session: DatabaseSession, settings: Settings, http_client: httpx.Client
    ) -> None:
        self.repository = SessionRepository(database_session)
        self.settings = settings
        self.client = AIModelClient(settings, http_client)

    def generate_request(
        self,
        *,
        question: Question,
        session: Session,
        main_draft: str,
        doubt_text: str | None,
    ) -> SupportRequestOutput | None:
        reasoning_effort = self.settings.ai_reasoning_effort
        result = self._generate(
            session=session,
            request_builder=lambda validation_errors: _render_support_prompt(
                question=question,
                session=session,
                main_draft=main_draft,
                doubt_text=doubt_text,
                validation_errors=validation_errors,
                model=self.settings.ai_model,
                prompt_version=self.settings.prompt_version,
                reasoning_effort=reasoning_effort,
            ),
            output_type=SupportRequestOutput,
            validator=_validate_support_request,
        )
        return result

    def assess_guided_answers(
        self,
        *,
        question: Question,
        session: Session,
        support_event: SupportEvent,
        answers: list[GuidedAnswer],
    ) -> GuidedAnswerAssessmentOutput | None:
        reasoning_effort = self.settings.ai_reasoning_effort
        result = self._generate(
            session=session,
            request_builder=lambda validation_errors: _render_answer_assessment_prompt(
                question=question,
                session=session,
                support_event=support_event,
                answers=answers,
                validation_errors=validation_errors,
                model=self.settings.ai_model,
                prompt_version=self.settings.prompt_version,
                reasoning_effort=reasoning_effort,
            ),
            output_type=GuidedAnswerAssessmentOutput,
            validator=lambda output: _validate_answer_assessment(output, support_event),
        )
        return result

    def _generate(
        self,
        *,
        session: Session,
        request_builder: Callable[[list[str]], ModelRequestSnapshot],
        output_type: type[OutputType],
        validator,
    ) -> OutputType | None:
        validation_errors: list[str] = []
        external_attempt_number = 0
        run_id = self._run_id(session)
        event_log = SessionEventLog(self.repository.database_session)
        for schema_attempt in range(self.settings.ai_schema_max_retries + 1):
            request = request_builder(validation_errors)
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
                    need_human_reason="AI 教学支持服务在配置的重试次数内未成功响应",
                    trigger_type="AI_SUPPORT_TRANSPORT_RETRY_EXHAUSTED",
                    run_id=run_id,
                )
                return None
            if external_call is None:
                raise RuntimeError("AI 教学支持传输成功后缺少外部调用记录")
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
                )
                logger.log(
                    logging.ERROR
                    if schema_attempt == self.settings.ai_schema_max_retries
                    else logging.WARNING,
                    "AI 教学支持输出校验失败",
                    extra={
                        "eventName": "ai.output.validation_failed",
                        "purpose": request.purpose,
                        "model": self.settings.ai_model,
                        "durationMs": model_response.duration_ms,
                        "errorType": "AI_SCHEMA_ERROR",
                    },
                )
                if schema_attempt == self.settings.ai_schema_max_retries:
                    self.repository.request_human_review(
                        session=session,
                        need_human_reason="AI 教学支持在配置的重试次数内仍不合法："
                        + "；".join(validation_errors),
                        trigger_type="AI_SUPPORT_SCHEMA_RETRY_EXHAUSTED",
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
            )
            logger.info(
                "AI 教学支持输出校验通过",
                extra={
                    "eventName": "ai.output.validated",
                    "purpose": request.purpose,
                    "model": self.settings.ai_model,
                    "durationMs": model_response.duration_ms,
                },
            )
            return output
        raise RuntimeError("AI 教学支持结构重试循环未产生结果")

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
                model_response = self.client.evaluate(request)
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
                    "AI 教学支持调用失败",
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
                "AI 教学支持调用完成",
                extra={
                    "eventName": "ai.call.completed",
                    "purpose": request.purpose,
                    "model": self.settings.ai_model,
                    "durationMs": model_response.duration_ms,
                },
            )
            return model_response, external_call, current_attempt_number, requested_event.event_id
        raise RuntimeError("AI 教学支持传输重试循环未产生结果")

    @staticmethod
    def _run_id(session: Session) -> str:
        return f"run_session_{session.id}_support_{session.version}"


def _render_support_prompt(
    *,
    question: Question,
    session: Session,
    main_draft: str,
    doubt_text: str | None,
    validation_errors: list[str],
    model: str,
    prompt_version: str,
    reasoning_effort: str | None = None,
) -> ModelRequestSnapshot:
    template = SUPPORT_PROMPT_PATH.read_text(encoding="utf-8")
    question_context = _question_context(question)
    session_context = _session_context(session)
    session_context["taskType"] = "HELP"
    user_input = {
        "mainDraft": main_draft,
        "doubtText": doubt_text,
    }
    context = {**question_context, **session_context, **user_input}
    prompt = template.replace("{{CONTEXT_JSON}}", json.dumps(context, ensure_ascii=False))
    prompt += "\n上一次结构校验错误：" + json.dumps(validation_errors, ensure_ascii=False)
    return _model_request(
        purpose="AI_SUPPORT",
        prompt_version=prompt_version,
        template=template,
        question_context=question_context,
        session_context=session_context,
        user_input=user_input,
        validation_errors=validation_errors,
        model=model,
        prompt=prompt,
        reasoning_effort=reasoning_effort,
    )


def _render_answer_assessment_prompt(
    *,
    question: Question,
    session: Session,
    support_event: SupportEvent,
    answers: list[GuidedAnswer],
    validation_errors: list[str],
    model: str,
    prompt_version: str,
    reasoning_effort: str | None = None,
) -> ModelRequestSnapshot:
    template = ASSESSMENT_PROMPT_PATH.read_text(encoding="utf-8")
    question_context = _question_context(question)
    session_context = _session_context(session)
    session_context["taskType"] = "GUIDED_ANSWER"
    user_input = {
        "mainDraft": support_event.main_draft,
        "questions": support_event.guided_questions,
        "answers": [answer.model_dump() for answer in answers],
    }
    context = {**question_context, **session_context, **user_input}
    prompt = template.replace("{{CONTEXT_JSON}}", json.dumps(context, ensure_ascii=False))
    prompt += "\n上一次结构校验错误：" + json.dumps(validation_errors, ensure_ascii=False)
    return _model_request(
        purpose="GUIDED_ANSWER_ASSESSMENT",
        prompt_version=prompt_version,
        template=template,
        question_context=question_context,
        session_context=session_context,
        user_input=user_input,
        validation_errors=validation_errors,
        model=model,
        prompt=prompt,
        reasoning_effort=reasoning_effort,
    )


def _question_context(question: Question) -> dict[str, object]:
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


def _session_context(session: Session) -> dict[str, object]:
    return {
        "round": session.round,
        "supportCountRound": session.support_count_round,
    }


def _model_request(
    *,
    purpose: str,
    prompt_version: str,
    template: str,
    question_context: dict[str, object],
    session_context: dict[str, object],
    user_input: dict[str, object],
    validation_errors: list[str],
    model: str,
    prompt: str,
    reasoning_effort: str | None = None,
) -> ModelRequestSnapshot:
    extra_body = resolve_reasoning_params(model, reasoning_effort)
    return ModelRequestSnapshot(
        purpose=purpose,
        prompt_version=prompt_version,
        blocks=ModelRequestBlocks(
            system_instructions=template,
            question_context=question_context,
            session_context=session_context,
            user_input=user_input,
            retry_context={"validationErrors": validation_errors},
        ),
        transport=ModelTransportSnapshot(
            model=model,
            messages=[ModelRequestMessage(role="user", content=prompt)],
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


def _validate_support_request(output: SupportRequestOutput) -> list[str]:
    no_reason = output.action == "REFUSE_FULL_SOLUTION"
    if no_reason and (
        output.main_reason is not None
        or output.other_reasons
        or output.judge_reason is not None
    ):
        return ["拒绝完整答案时不能返回困难原因"]
    if not no_reason and (output.main_reason is None or output.judge_reason is None):
        return ["非拒答支持必须返回具体困难原因和判断依据"]
    if output.action == "GUIDED_QUESTIONS" and not output.questions:
        return ["GUIDED_QUESTIONS 必须提供至少一个子问题"]
    if output.action != "GUIDED_QUESTIONS" and output.questions:
        return ["非子问题动作不能提供 questions"]
    question_ids = [question.id for question in output.questions]
    if len(question_ids) != len(set(question_ids)):
        return ["questions 的 id 不能重复"]
    return []


def _validate_answer_assessment(
    output: GuidedAnswerAssessmentOutput, support_event: SupportEvent
) -> list[str]:
    expected_ids = {item["id"] for item in support_event.guided_questions or []}
    result_ids = [item.question_id for item in output.results]
    if set(result_ids) != expected_ids or len(result_ids) != len(expected_ids):
        return ["子问题评估结果必须与已发送问题一一对应"]
    all_correct = all(item.result == "CORRECT" for item in output.results)
    if all_correct and (
        output.main_reason is not None
        or output.other_reasons
        or output.judge_reason is not None
    ):
        return ["子问题全部答对时不能返回困难原因"]
    if not all_correct and (output.main_reason is None or output.judge_reason is None):
        return ["存在错误或不完整作答时必须返回具体困难原因和判断依据"]
    return []
