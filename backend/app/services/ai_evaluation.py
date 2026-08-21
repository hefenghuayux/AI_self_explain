import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import ValidationError
from sqlalchemy.orm import Session as DatabaseSession

from app.core.config import Settings
from app.models.ai_evaluation import AIEvaluation
from app.models.explanation_attempt import ExplanationAttempt
from app.models.external_call_record import ExternalCallRecord
from app.models.question import Question
from app.models.session import Session
from app.repositories.sessions import SessionRepository, session_run_id
from app.schemas.ai_evaluation import (
    AIEvaluationOutput,
    evaluation_json_schema,
    validate_evaluation_relationships,
)
from app.schemas.model_request_snapshot import (
    ModelRequestBlocks,
    ModelRequestMessage,
    ModelRequestPrivacy,
    ModelRequestSnapshot,
    ModelTransportSnapshot,
)
from app.services.session_event_log import SessionEventLog

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "evaluate_explanation.md"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AIModelResponse:
    raw_response: str
    content: str
    duration_ms: int


class AITransportError(RuntimeError):
    def __init__(
        self,
        *,
        error_type: str,
        message: str,
        duration_ms: int,
        raw_response: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.duration_ms = duration_ms
        self.raw_response = raw_response


class AIModelClient:
    def __init__(self, settings: Settings, http_client: httpx.Client) -> None:
        self.settings = settings
        self.http_client = http_client

    def evaluate(self, request: ModelRequestSnapshot) -> AIModelResponse:
        started_at = time.perf_counter()
        endpoint = f"{str(self.settings.ai_base_url).rstrip('/')}/chat/completions"
        try:
            response = self.http_client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {self.settings.ai_api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
                # DeepSeek 当前只支持 JSON object 模式。动态 Schema 仍在提示词和
                # 本地校验中严格执行；这里直接发送审计快照中的真实 transport。
                json=request.transport_payload(),
            )
        except httpx.TimeoutException as error:
            raise AITransportError(
                error_type="AI_TIMEOUT",
                message=f"AI 请求超时：{error}",
                duration_ms=_duration_ms(started_at),
            ) from error
        except httpx.RequestError as error:
            raise AITransportError(
                error_type="AI_SERVICE_ERROR",
                message=f"AI 服务请求失败：{error}",
                duration_ms=_duration_ms(started_at),
            ) from error

        raw_response = response.text
        if response.is_error:
            raise AITransportError(
                error_type="AI_SERVICE_ERROR",
                message=f"AI 服务返回 HTTP {response.status_code}",
                duration_ms=_duration_ms(started_at),
                raw_response=raw_response,
            )
        try:
            response_body = response.json()
            content = response_body["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise AITransportError(
                error_type="AI_SERVICE_ERROR",
                message=f"AI 服务响应不包含可解析的 choices[0].message.content：{error}",
                duration_ms=_duration_ms(started_at),
                raw_response=raw_response,
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise AITransportError(
                error_type="AI_SERVICE_ERROR",
                message="AI 服务响应中的 choices[0].message.content 不能为空字符串",
                duration_ms=_duration_ms(started_at),
                raw_response=raw_response,
            )
        return AIModelResponse(
            raw_response=raw_response,
            content=content,
            duration_ms=_duration_ms(started_at),
        )


class AIEvaluationService:
    def __init__(
        self, database_session: DatabaseSession, settings: Settings, http_client: httpx.Client
    ) -> None:
        self.repository = SessionRepository(database_session)
        self.settings = settings
        self.client = AIModelClient(settings, http_client)

    def evaluate(
        self,
        *,
        question: Question,
        session: Session,
        attempt: ExplanationAttempt,
    ) -> AIEvaluation | Session:
        schema = evaluation_json_schema(question.rubric_points)
        validation_errors: list[str] = []
        external_attempt_number = 0
        run_id = session_run_id(session.id, attempt.id)
        event_log = SessionEventLog(self.repository.database_session)

        for schema_attempt in range(self.settings.ai_schema_max_retries + 1):
            request = _render_prompt(
                question=question,
                session=session,
                attempt=attempt,
                schema=schema,
                validation_errors=validation_errors,
                model=self.settings.ai_model,
                prompt_version=self.settings.prompt_version,
            )
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
                )
            )
            if model_response is None:
                return self.repository.request_human_review(
                    session=session,
                    need_human_reason="AI 评价服务在配置的重试次数内未成功响应",
                    trigger_type="AI_EVALUATION_TRANSPORT_RETRY_EXHAUSTED",
                    related_attempt_id=attempt.id,
                    run_id=run_id,
                )

            if external_call is None:
                raise RuntimeError("AI 评价传输成功后缺少外部调用记录")
            evaluation, validation_errors = _parse_and_validate_evaluation(
                model_response.content,
                question.rubric_points,
                attempt.confirmed_text,
            )
            if validation_errors:
                event_log.append_model_responded(
                    session_id=session.id,
                    run_id=run_id,
                    response_content=model_response.content,
                    validation="invalid",
                    duration_ms=model_response.duration_ms,
                    parent_event_id=requested_event_id,
                )
                self.repository.record_external_call_validation(
                    record=external_call,
                    validation_status="INVALID",
                    validation_errors=validation_errors,
                )
                logger.log(
                    logging.ERROR
                    if schema_attempt == self.settings.ai_schema_max_retries
                    else logging.WARNING,
                    "AI 评价输出校验失败",
                    extra={
                        "eventName": "ai.output.validation_failed",
                        "purpose": request.purpose,
                        "model": self.settings.ai_model,
                        "durationMs": model_response.duration_ms,
                        "errorType": "AI_SCHEMA_ERROR",
                    },
                )
                invalid_evaluation = self.repository.record_invalid_evaluation(
                    session=session,
                    attempt=attempt,
                    evaluation=evaluation,
                    raw_response=model_response.raw_response,
                    validation_errors=validation_errors,
                    request_duration_ms=model_response.duration_ms,
                    prompt_version=self.settings.prompt_version,
                    model_provider=self.settings.ai_provider,
                    model_name=self.settings.ai_model,
                    external_call_record_id=external_call.id,
                )
                if schema_attempt == self.settings.ai_schema_max_retries:
                    reason = "AI 结构化评价在配置的重试次数内仍不合法：" + "；".join(
                        validation_errors
                    )
                    return self.repository.request_human_review(
                        session=session,
                        need_human_reason=reason,
                        trigger_type="AI_EVALUATION_SCHEMA_RETRY_EXHAUSTED",
                        related_attempt_id=attempt.id,
                        related_evaluation_id=invalid_evaluation.id,
                    )
                continue

            if evaluation is None:
                raise RuntimeError("AI 评价校验完成后缺少评价结果")
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
                "AI 评价输出校验通过",
                extra={
                    "eventName": "ai.output.validated",
                    "purpose": request.purpose,
                    "model": self.settings.ai_model,
                    "durationMs": model_response.duration_ms,
                },
            )
            return self.repository.record_valid_evaluation(
                session=session,
                attempt=attempt,
                evaluation=evaluation,
                raw_response=model_response.raw_response,
                request_duration_ms=model_response.duration_ms,
                prompt_version=self.settings.prompt_version,
                model_provider=self.settings.ai_provider,
                model_name=self.settings.ai_model,
                external_call_record_id=external_call.id,
            )
        raise RuntimeError("AI 结构化评价循环未产生结果")

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
                    "AI 评价调用失败",
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
                attempt_number=current_attempt_number,
                transport_status="SUCCESS",
                duration_ms=model_response.duration_ms,
                provider=self.settings.ai_provider,
                model=self.settings.ai_model,
                raw_response=model_response.raw_response,
                request_snapshot=request,
            )
            logger.info(
                "AI 评价调用完成",
                extra={
                    "eventName": "ai.call.completed",
                    "purpose": request.purpose,
                    "model": self.settings.ai_model,
                    "durationMs": model_response.duration_ms,
                },
            )
            return model_response, external_call, current_attempt_number, requested_event.event_id
        raise RuntimeError("AI 传输重试循环未产生结果")


def _render_prompt(
    *,
    question: Question,
    session: Session,
    attempt: ExplanationAttempt,
    schema: dict[str, object],
    validation_errors: list[str],
    model: str,
    prompt_version: str,
) -> ModelRequestSnapshot:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    question_context: dict[str, object] = {
        "questionContent": question.question_content,
        "standardAnswer": question.standard_answer,
        "rubricPoints": question.rubric_points,
        "commonErrors": question.common_errors,
        "alternativeSolutions": question.alternative_solutions,
        "layeredHints": question.layered_hints,
        "guidedQuestions": question.guided_questions,
        "fullSolution": question.full_solution,
        "outputSchema": schema,
    }
    user_input: dict[str, object] = {
        "confirmedText": attempt.confirmed_text,
    }
    transport_context = {
        key: value for key, value in question_context.items() if key != "outputSchema"
    }
    transport_context.update(user_input)
    prompt = (
        template.replace("{{JSON_SCHEMA}}", json.dumps(schema, ensure_ascii=False))
        .replace("{{CONTEXT_JSON}}", json.dumps(transport_context, ensure_ascii=False))
        .replace("{{VALIDATION_ERRORS}}", json.dumps(validation_errors, ensure_ascii=False))
    )
    return ModelRequestSnapshot(
        purpose="AI_EVALUATION",
        prompt_version=prompt_version,
        blocks=ModelRequestBlocks(
            system_instructions=template,
            question_context=question_context,
            session_context={
                "round": session.round,
                "supportCountRound": session.support_count_round,
                "coveredPointsCurrentRound": session.covered_points_current_round,
            },
            user_input=user_input,
            retry_context={"validationErrors": validation_errors},
        ),
        transport=ModelTransportSnapshot(
            model=model,
            messages=[ModelRequestMessage(role="user", content=prompt)],
            response_format={"type": "json_object"},
        ),
        privacy=ModelRequestPrivacy(
            contains_student_content=True,
            contains_answer_material=True,
            contains_memory=False,
        ),
    )


def _parse_and_validate_evaluation(
    content: str,
    rubric_points: list[str],
    confirmed_text: str,
) -> tuple[AIEvaluationOutput | None, list[str]]:
    try:
        evaluation = AIEvaluationOutput.model_validate_json(content)
    except ValidationError as error:
        return None, [entry["msg"] for entry in error.errors()]
    return evaluation, validate_evaluation_relationships(evaluation, rubric_points, confirmed_text)


def _duration_ms(started_at: float) -> int:
    return round((time.perf_counter() - started_at) * 1000)
