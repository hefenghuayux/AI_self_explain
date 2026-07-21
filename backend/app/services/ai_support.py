import json
import time
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError
from sqlalchemy.orm import Session as DatabaseSession

from app.core.config import Settings
from app.models.question import Question
from app.models.session import Session
from app.models.support_event import SupportEvent
from app.repositories.sessions import SessionRepository
from app.schemas.support import (
    GuidedAnswer,
    GuidedAnswerAssessmentOutput,
    SupportRequestOutput,
)
from app.services.ai_evaluation import AIModelClient, AIModelResponse, AITransportError

SUPPORT_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "generate_support.md"
ASSESSMENT_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "assess_guided_answers.md"
)
OutputType = TypeVar("OutputType", SupportRequestOutput, GuidedAnswerAssessmentOutput)


class AISupportService:
    def __init__(self, database_session: DatabaseSession, settings: Settings) -> None:
        self.repository = SessionRepository(database_session)
        self.settings = settings
        self.client = AIModelClient(settings)

    def generate_request(
        self,
        *,
        question: Question,
        session: Session,
        main_draft: str,
        doubt_text: str | None,
        force_current_step: bool,
    ) -> SupportRequestOutput | None:
        prompt = _render_support_prompt(
            question=question,
            session=session,
            main_draft=main_draft,
            doubt_text=doubt_text,
            force_current_step=force_current_step,
        )
        result = self._generate(
            session=session,
            prompt=prompt,
            output_type=SupportRequestOutput,
            validator=lambda output: _validate_support_request(output, question.rubric_points),
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
        prompt = _render_answer_assessment_prompt(
            question=question,
            session=session,
            support_event=support_event,
            answers=answers,
        )
        result = self._generate(
            session=session,
            prompt=prompt,
            output_type=GuidedAnswerAssessmentOutput,
            validator=lambda output: _validate_answer_assessment(output, support_event),
        )
        return result

    def _generate(
        self,
        *,
        session: Session,
        prompt: str,
        output_type: type[OutputType],
        validator,
    ) -> OutputType | None:
        validation_errors: list[str] = []
        external_attempt_number = 0
        for schema_attempt in range(self.settings.ai_schema_max_retries + 1):
            model_response, external_attempt_number = self._call_with_transport_retries(
                session=session,
                prompt=(
                    prompt
                    + "\n上一次结构校验错误："
                    + json.dumps(validation_errors, ensure_ascii=False)
                ),
                external_attempt_number=external_attempt_number,
            )
            if model_response is None:
                self.repository.return_to_wait_student_action_after_support_failure(
                    session=session, trigger_type="AI_SUPPORT_TRANSPORT_RETRY_EXHAUSTED"
                )
                return None
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
                    self.repository.mark_support_schema_retry_exhausted(
                        session=session,
                        need_human_reason="AI 教学支持在配置的重试次数内仍不合法："
                        + "；".join(validation_errors),
                    )
                    return None
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
            return output
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


def _render_support_prompt(
    *,
    question: Question,
    session: Session,
    main_draft: str,
    doubt_text: str | None,
    force_current_step: bool,
) -> str:
    context = _base_context(question=question, session=session)
    context.update(
        {
            "mainDraft": main_draft,
            "doubtText": doubt_text,
            "forceCurrentStepAnswer": force_current_step,
        }
    )
    return SUPPORT_PROMPT_PATH.read_text(encoding="utf-8").replace(
        "{{CONTEXT_JSON}}", json.dumps(context, ensure_ascii=False)
    )


def _render_answer_assessment_prompt(
    *,
    question: Question,
    session: Session,
    support_event: SupportEvent,
    answers: list[GuidedAnswer],
) -> str:
    context = _base_context(question=question, session=session)
    context.update(
        {
            "mainDraft": support_event.main_draft,
            "questions": support_event.guided_questions,
            "answers": [answer.model_dump() for answer in answers],
        }
    )
    return ASSESSMENT_PROMPT_PATH.read_text(encoding="utf-8").replace(
        "{{CONTEXT_JSON}}", json.dumps(context, ensure_ascii=False)
    )


def _base_context(*, question: Question, session: Session) -> dict[str, object]:
    return {
        "questionContent": question.question_content,
        "standardAnswer": question.standard_answer,
        "rubricPoints": question.rubric_points,
        "commonErrors": question.common_errors,
        "alternativeSolutions": question.alternative_solutions,
        "layeredHints": question.layered_hints,
        "guidedQuestions": question.guided_questions,
        "fullSolution": question.full_solution,
        "round": session.round,
        "supportCountRound": session.support_count_round,
        "coveredPointsCurrentRound": session.covered_points_current_round,
    }


def _validate_support_request(output: SupportRequestOutput, rubric_points: list[str]) -> list[str]:
    covered_points = set(output.covered_points)
    missing_points = set(output.missing_points)
    expected_points = set(rubric_points)
    if covered_points & missing_points or covered_points | missing_points != expected_points:
        return ["coveredPoints 与 missingPoints 必须无重叠且完整覆盖题目评分点"]
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
    return []
