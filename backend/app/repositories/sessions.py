from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from app.models.ai_evaluation import AIEvaluation
from app.models.explanation_attempt import ExplanationAttempt
from app.models.external_call_record import ExternalCallRecord
from app.models.session import Session
from app.models.state_transition_event import StateTransitionEvent
from app.rules.session_lifecycle import (
    FLOW_STAGE_AI_EVALUATING,
    FLOW_STAGE_CONFIRMING_TEXT,
    FLOW_STAGE_WAIT_INITIAL_CHOICE,
    FLOW_STAGE_WAIT_STUDENT_ACTION,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_NEED_HUMAN,
    flow_stage_after_initial_choice,
)
from app.schemas.ai_evaluation import AIEvaluationOutput


def session_snapshot(session: Session) -> dict[str, object]:
    return {
        "status": session.status,
        "flowStage": session.flow_stage,
        "round": session.round,
        "supportCountRound": session.support_count_round,
        "supportCountTotal": session.support_count_total,
        "noProgressCount": session.no_progress_count,
        "solutionExposed": session.solution_exposed,
        "completionType": session.completion_type,
        "needHumanReason": session.need_human_reason,
        "coveredPointsCurrentRound": session.covered_points_current_round,
        "coveredPointsAll": session.covered_points_all,
        "version": session.version,
    }


class SessionRepository:
    def __init__(self, database_session: DatabaseSession) -> None:
        self.database_session = database_session

    def create(self, question_id: int) -> Session:
        session = Session(
            question_id=question_id,
            status=STATUS_IN_PROGRESS,
            flow_stage=FLOW_STAGE_WAIT_INITIAL_CHOICE,
            round=1,
            support_count_round=0,
            support_count_total=0,
            no_progress_count=0,
            solution_exposed=False,
            covered_points_current_round=[],
            covered_points_all=[],
            version=0,
        )
        self.database_session.add(session)
        self.database_session.flush()
        self.database_session.add(
            StateTransitionEvent(
                session_id=session.id,
                trigger_type="CREATE_SESSION",
                from_status="NEW",
                to_status=session.status,
                from_flow_stage=None,
                to_flow_stage=session.flow_stage,
                before_snapshot={"status": "NEW", "flowStage": None},
                after_snapshot=session_snapshot(session),
            )
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def get(self, session_id: int) -> Session | None:
        return self.database_session.get(Session, session_id)

    def get_latest_attempt(self, session_id: int) -> ExplanationAttempt | None:
        statement = (
            select(ExplanationAttempt)
            .where(ExplanationAttempt.session_id == session_id)
            .order_by(ExplanationAttempt.id.desc())
        )
        return self.database_session.scalars(statement).first()

    def get_latest_valid_evaluation(self, session_id: int) -> AIEvaluation | None:
        statement = (
            select(AIEvaluation)
            .where(
                AIEvaluation.session_id == session_id,
                AIEvaluation.validation_status == "VALID",
            )
            .order_by(AIEvaluation.id.desc())
        )
        return self.database_session.scalars(statement).first()

    def choose_initial_choice(self, session: Session, choice: str) -> Session:
        before_snapshot = session_snapshot(session)
        session.initial_choice = choice
        session.flow_stage = flow_stage_after_initial_choice(choice)
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="SELECT_INITIAL_CHOICE",
            before_snapshot=before_snapshot,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def submit_text(
        self, session: Session, confirmed_text: str
    ) -> tuple[Session, ExplanationAttempt]:
        before_snapshot = session_snapshot(session)
        attempt = ExplanationAttempt(
            session_id=session.id,
            round=session.round,
            input_mode="TEXT",
            confirmed_text=confirmed_text,
            confirmed_at=datetime.now(UTC),
        )
        self.database_session.add(attempt)
        self.database_session.flush()
        session.flow_stage = FLOW_STAGE_AI_EVALUATING
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="SUBMIT_TEXT",
            before_snapshot=before_snapshot,
            related_attempt_id=attempt.id,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        self.database_session.refresh(attempt)
        return session, attempt

    def begin_ai_evaluation(self, session: Session, attempt: ExplanationAttempt) -> Session:
        before_snapshot = session_snapshot(session)
        session.flow_stage = FLOW_STAGE_AI_EVALUATING
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="RETRY_AI_EVALUATION",
            before_snapshot=before_snapshot,
            related_attempt_id=attempt.id,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def record_external_call(
        self,
        *,
        session: Session,
        attempt_number: int,
        status: str,
        duration_ms: int,
        provider: str,
        model: str,
        error_type: str | None = None,
        error_message: str | None = None,
        raw_response: str | None = None,
    ) -> None:
        self.database_session.add(
            ExternalCallRecord(
                session_id=session.id,
                call_type="AI_EVALUATION",
                provider=provider,
                model=model,
                attempt_number=attempt_number,
                status=status,
                duration_ms=duration_ms,
                error_type=error_type,
                error_message=error_message,
                raw_response=raw_response,
            )
        )
        self.database_session.commit()

    def record_invalid_evaluation(
        self,
        *,
        session: Session,
        attempt: ExplanationAttempt,
        evaluation: AIEvaluationOutput | None,
        raw_response: str,
        validation_errors: list[str],
        request_duration_ms: int,
        prompt_version: str,
        model_provider: str,
        model_name: str,
    ) -> AIEvaluation:
        saved_evaluation = self._create_evaluation(
            session=session,
            attempt=attempt,
            evaluation=evaluation,
            raw_response=raw_response,
            validation_status="INVALID",
            validation_errors=validation_errors,
            request_duration_ms=request_duration_ms,
            prompt_version=prompt_version,
            model_provider=model_provider,
            model_name=model_name,
        )
        self.database_session.commit()
        self.database_session.refresh(saved_evaluation)
        return saved_evaluation

    def apply_valid_evaluation(
        self,
        *,
        session: Session,
        attempt: ExplanationAttempt,
        evaluation: AIEvaluationOutput,
        raw_response: str,
        request_duration_ms: int,
        prompt_version: str,
        model_provider: str,
        model_name: str,
    ) -> Session:
        before_snapshot = session_snapshot(session)
        saved_evaluation = self._create_evaluation(
            session=session,
            attempt=attempt,
            evaluation=evaluation,
            raw_response=raw_response,
            validation_status="VALID",
            validation_errors=[],
            request_duration_ms=request_duration_ms,
            prompt_version=prompt_version,
            model_provider=model_provider,
            model_name=model_name,
        )
        self.database_session.flush()
        if evaluation.next_action == "COMPLETE":
            session.status = STATUS_COMPLETED
            session.completion_type = completion_type_for(session)
            session.finished_at = datetime.now(UTC)
        elif evaluation.next_action == "NEED_HUMAN":
            session.status = STATUS_NEED_HUMAN
            session.need_human_reason = evaluation.need_human_reason
            session.finished_at = datetime.now(UTC)
        session.flow_stage = FLOW_STAGE_WAIT_STUDENT_ACTION
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="APPLY_AI_EVALUATION",
            before_snapshot=before_snapshot,
            related_attempt_id=attempt.id,
            related_evaluation_id=saved_evaluation.id,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def return_to_confirming_text(
        self,
        *,
        session: Session,
        attempt: ExplanationAttempt,
    ) -> Session:
        before_snapshot = session_snapshot(session)
        session.flow_stage = FLOW_STAGE_CONFIRMING_TEXT
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="AI_TRANSPORT_RETRY_EXHAUSTED",
            before_snapshot=before_snapshot,
            related_attempt_id=attempt.id,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def mark_schema_retry_exhausted(
        self,
        *,
        session: Session,
        attempt: ExplanationAttempt,
        evaluation: AIEvaluation,
        need_human_reason: str,
    ) -> Session:
        before_snapshot = session_snapshot(session)
        session.status = STATUS_NEED_HUMAN
        session.flow_stage = FLOW_STAGE_WAIT_STUDENT_ACTION
        session.need_human_reason = need_human_reason
        session.finished_at = datetime.now(UTC)
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="AI_SCHEMA_RETRY_EXHAUSTED",
            before_snapshot=before_snapshot,
            related_attempt_id=attempt.id,
            related_evaluation_id=evaluation.id,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def _create_evaluation(
        self,
        *,
        session: Session,
        attempt: ExplanationAttempt,
        evaluation: AIEvaluationOutput | None,
        raw_response: str,
        validation_status: str,
        validation_errors: list[str],
        request_duration_ms: int,
        prompt_version: str,
        model_provider: str,
        model_name: str,
    ) -> AIEvaluation:
        saved_evaluation = AIEvaluation(
            session_id=session.id,
            attempt_id=attempt.id,
            correctness=evaluation.correctness if evaluation is not None else None,
            completeness=evaluation.completeness if evaluation is not None else None,
            covered_points=evaluation.covered_points if evaluation is not None else None,
            missing_points=evaluation.missing_points if evaluation is not None else None,
            error_evidence=[item.model_dump() for item in evaluation.error_evidence]
            if evaluation is not None
            else None,
            feedback=evaluation.feedback if evaluation is not None else None,
            confidence=float(evaluation.confidence) if evaluation is not None else None,
            next_action=evaluation.next_action if evaluation is not None else None,
            need_human_reason=evaluation.need_human_reason if evaluation is not None else None,
            prompt_version=prompt_version,
            model_provider=model_provider,
            model_name=model_name,
            raw_response=raw_response,
            validation_status=validation_status,
            validation_errors=validation_errors,
            request_duration_ms=request_duration_ms,
        )
        self.database_session.add(saved_evaluation)
        return saved_evaluation

    def _record_transition(
        self,
        *,
        session: Session,
        trigger_type: str,
        before_snapshot: dict[str, object],
        related_attempt_id: int | None = None,
        related_evaluation_id: int | None = None,
    ) -> None:
        self.database_session.add(
            StateTransitionEvent(
                session_id=session.id,
                trigger_type=trigger_type,
                from_status=str(before_snapshot["status"]),
                to_status=session.status,
                from_flow_stage=str(before_snapshot["flowStage"])
                if before_snapshot["flowStage"] is not None
                else None,
                to_flow_stage=session.flow_stage,
                before_snapshot=before_snapshot,
                after_snapshot=session_snapshot(session),
                related_attempt_id=related_attempt_id,
                related_evaluation_id=related_evaluation_id,
            )
        )


def completion_type_for(session: Session) -> str:
    if session.solution_exposed and session.round == 2:
        return "AFTER_SOLUTION"
    if session.support_count_total > 0:
        return "WITH_SUPPORT"
    return "INDEPENDENT"
