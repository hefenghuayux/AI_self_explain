import json
import time
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session as DatabaseSession

from app.core.config import Settings
from app.models.question import Question
from app.models.session import Session
from app.repositories.sessions import SessionRepository
from app.schemas.support import SupportContentOutput
from app.services.ai_evaluation import AIModelClient, AIModelResponse, AITransportError

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "generate_support.md"


class AISupportService:
    def __init__(self, database_session: DatabaseSession, settings: Settings) -> None:
        self.repository = SessionRepository(database_session)
        self.settings = settings
        self.client = AIModelClient(settings)

    def generate_hint(self, *, question: Question, session: Session) -> Session:
        validation_errors: list[str] = []
        external_attempt_number = 0
        latest_evaluation = self.repository.get_latest_valid_evaluation(session.id)
        for schema_attempt in range(self.settings.ai_schema_max_retries + 1):
            prompt = _render_prompt(
                question=question,
                session=session,
                validation_errors=validation_errors,
                latest_evaluation=latest_evaluation,
            )
            model_response, external_attempt_number = self._call_with_transport_retries(
                session=session,
                prompt=prompt,
                external_attempt_number=external_attempt_number,
            )
            if model_response is None:
                return self.repository.return_to_wait_student_action_after_support_failure(
                    session=session, trigger_type="AI_SUPPORT_TRANSPORT_RETRY_EXHAUSTED"
                )
            try:
                output = SupportContentOutput.model_validate_json(model_response.content)
            except ValidationError as error:
                validation_errors = [entry["msg"] for entry in error.errors()]
                self.repository.record_external_call(
                    session=session,
                    call_type="AI_SUPPORT",
                    attempt_number=external_attempt_number,
                    status="ERROR",
                    duration_ms=model_response.duration_ms,
                    provider=self.settings.ai_provider,
                    model=self.settings.ai_model,
                    error_type="AI_SCHEMA_ERROR",
                    error_message="；".join(validation_errors),
                    raw_response=model_response.raw_response,
                )
                if schema_attempt == self.settings.ai_schema_max_retries:
                    reason = "AI 教学支持在配置的重试次数内仍不合法：" + "；".join(
                        validation_errors
                    )
                    return self.repository.mark_support_schema_retry_exhausted(
                        session=session, need_human_reason=reason
                    )
                continue
            self.repository.record_external_call(
                session=session,
                call_type="AI_SUPPORT",
                attempt_number=external_attempt_number,
                status="SUCCESS",
                duration_ms=model_response.duration_ms,
                provider=self.settings.ai_provider,
                model=self.settings.ai_model,
                raw_response=model_response.raw_response,
            )
            return self.repository.record_generated_hint(
                session=session, content=output.content, settings=self.settings
            )
        raise RuntimeError("AI 教学支持结构重试循环未产生结果")

    def _call_with_transport_retries(
        self, *, session: Session, prompt: str, external_attempt_number: int
    ) -> tuple[AIModelResponse | None, int]:
        for transport_attempt in range(self.settings.ai_transport_max_retries + 1):
            current_attempt_number = external_attempt_number + 1
            try:
                model_response = self.client.evaluate(prompt, {"type": "object"})
            except AITransportError as error:
                self.repository.record_external_call(
                    session=session,
                    call_type="AI_SUPPORT",
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
            return model_response, current_attempt_number
        raise RuntimeError("AI 教学支持传输重试循环未产生结果")


def _render_prompt(
    *,
    question: Question,
    session: Session,
    validation_errors: list[str],
    latest_evaluation: object | None,
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
        "latestEvaluation": _evaluation_context(latest_evaluation),
    }
    return (
        template.replace("{{CONTEXT_JSON}}", json.dumps(context, ensure_ascii=False))
        + "\n上一次结构校验错误："
        + json.dumps(validation_errors, ensure_ascii=False)
    )


def _evaluation_context(evaluation: object | None) -> dict[str, object] | None:
    if evaluation is None:
        return None
    return {
        "correctness": evaluation.correctness,
        "completeness": evaluation.completeness,
        "coveredPoints": evaluation.covered_points,
        "missingPoints": evaluation.missing_points,
        "feedback": evaluation.feedback,
        "nextAction": evaluation.next_action,
    }
