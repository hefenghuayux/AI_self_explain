import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import ValidationError
from sqlalchemy.orm import Session as DatabaseSession

from app.core.config import Settings
from app.models.explanation_attempt import ExplanationAttempt
from app.models.question import Question
from app.models.session import Session
from app.repositories.sessions import SessionRepository
from app.schemas.ai_evaluation import (
    AIEvaluationOutput,
    evaluation_json_schema,
    validate_evaluation_relationships,
)

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "evaluate_explanation.md"


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
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(self, prompt: str, schema: dict[str, object]) -> AIModelResponse:
        started_at = time.perf_counter()
        endpoint = f"{str(self.settings.ai_base_url).rstrip('/')}/chat/completions"
        try:
            with httpx.Client(timeout=self.settings.ai_request_timeout_seconds) as client:
                response = client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self.settings.ai_api_key.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.settings.ai_model,
                        "messages": [{"role": "user", "content": prompt}],
                        # DeepSeek 当前只支持 JSON object 模式。
                        # 动态 Schema 仍在提示词和本地校验中严格执行。
                        "response_format": {"type": "json_object"},
                    },
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
    def __init__(self, database_session: DatabaseSession, settings: Settings) -> None:
        self.repository = SessionRepository(database_session)
        self.settings = settings
        self.client = AIModelClient(settings)

    def evaluate(
        self,
        *,
        question: Question,
        session: Session,
        attempt: ExplanationAttempt,
    ) -> Session:
        schema = evaluation_json_schema(question.rubric_points)
        validation_errors: list[str] = []
        external_attempt_number = 0

        for schema_attempt in range(self.settings.ai_schema_max_retries + 1):
            prompt = _render_prompt(
                question=question,
                session=session,
                attempt=attempt,
                schema=schema,
                validation_errors=validation_errors,
            )
            model_response, external_attempt_number = self._call_with_transport_retries(
                session=session,
                prompt=prompt,
                schema=schema,
                external_attempt_number=external_attempt_number,
            )
            if model_response is None:
                return self.repository.return_to_confirming_text(session=session, attempt=attempt)

            evaluation, validation_errors = _parse_and_validate_evaluation(
                model_response.content,
                question.rubric_points,
                attempt.confirmed_text,
            )
            if validation_errors:
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
                )
                if schema_attempt == self.settings.ai_schema_max_retries:
                    reason = "AI 结构化评价在配置的重试次数内仍不合法：" + "；".join(
                        validation_errors
                    )
                    return self.repository.mark_schema_retry_exhausted(
                        session=session,
                        attempt=attempt,
                        evaluation=invalid_evaluation,
                        need_human_reason=reason,
                    )
                continue

            if evaluation is None:
                raise RuntimeError("AI 评价校验完成后缺少评价结果")
            return self.repository.apply_valid_evaluation(
                session=session,
                attempt=attempt,
                evaluation=evaluation,
                raw_response=model_response.raw_response,
                request_duration_ms=model_response.duration_ms,
                prompt_version=self.settings.prompt_version,
                model_provider=self.settings.ai_provider,
                model_name=self.settings.ai_model,
                settings=self.settings,
            )
        raise RuntimeError("AI 结构化评价循环未产生结果")

    def _call_with_transport_retries(
        self,
        *,
        session: Session,
        prompt: str,
        schema: dict[str, object],
        external_attempt_number: int,
    ) -> tuple[AIModelResponse | None, int]:
        for transport_attempt in range(self.settings.ai_transport_max_retries + 1):
            current_attempt_number = external_attempt_number + 1
            try:
                model_response = self.client.evaluate(prompt, schema)
            except AITransportError as error:
                self.repository.record_external_call(
                    session=session,
                    attempt_number=current_attempt_number,
                    status="ERROR",
                    duration_ms=error.duration_ms,
                    provider=self.settings.ai_provider,
                    model=self.settings.ai_model,
                    error_type=error.error_type,
                    error_message=str(error),
                    raw_response=error.raw_response,
                )
                if transport_attempt == self.settings.ai_transport_max_retries:
                    return None, current_attempt_number
                time.sleep(self.settings.ai_retry_backoff_seconds[transport_attempt])
                external_attempt_number = current_attempt_number
                continue

            self.repository.record_external_call(
                session=session,
                attempt_number=current_attempt_number,
                status="SUCCESS",
                duration_ms=model_response.duration_ms,
                provider=self.settings.ai_provider,
                model=self.settings.ai_model,
                raw_response=model_response.raw_response,
            )
            return model_response, current_attempt_number
        raise RuntimeError("AI 传输重试循环未产生结果")


def _render_prompt(
    *,
    question: Question,
    session: Session,
    attempt: ExplanationAttempt,
    schema: dict[str, object],
    validation_errors: list[str],
) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    context = {
        "questionContent": question.question_content,
        "standardAnswer": question.standard_answer,
        "rubricPoints": question.rubric_points,
        "commonErrors": question.common_errors,
        "alternativeSolutions": question.alternative_solutions,
        "layeredHints": question.layered_hints,
        "fullSolution": question.full_solution,
        "round": session.round,
        "supportCountRound": session.support_count_round,
        "coveredPointsCurrentRound": session.covered_points_current_round,
        "confirmedText": attempt.confirmed_text,
    }
    return (
        template.replace("{{JSON_SCHEMA}}", json.dumps(schema, ensure_ascii=False))
        .replace("{{CONTEXT_JSON}}", json.dumps(context, ensure_ascii=False))
        .replace("{{VALIDATION_ERRORS}}", json.dumps(validation_errors, ensure_ascii=False))
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
