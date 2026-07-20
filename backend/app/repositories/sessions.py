from datetime import UTC, datetime

from sqlalchemy.orm import Session as DatabaseSession

from app.models.explanation_attempt import ExplanationAttempt
from app.models.session import Session
from app.models.state_transition_event import StateTransitionEvent
from app.rules.session_lifecycle import (
    FLOW_STAGE_AI_EVALUATING,
    FLOW_STAGE_WAIT_INITIAL_CHOICE,
    STATUS_IN_PROGRESS,
    flow_stage_after_initial_choice,
)


def session_snapshot(session: Session) -> dict[str, object]:
    return {
        "status": session.status,
        "flowStage": session.flow_stage,
        "round": session.round,
        "supportCountRound": session.support_count_round,
        "supportCountTotal": session.support_count_total,
        "noProgressCount": session.no_progress_count,
        "solutionExposed": session.solution_exposed,
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

    def submit_text(self, session: Session, confirmed_text: str) -> Session:
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
        return session

    def _record_transition(
        self,
        *,
        session: Session,
        trigger_type: str,
        before_snapshot: dict[str, object],
        related_attempt_id: int | None = None,
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
            )
        )
