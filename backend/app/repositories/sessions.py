from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from app.core.config import Settings
from app.models.ai_evaluation import AIEvaluation
from app.models.explanation_attempt import ExplanationAttempt
from app.models.external_call_record import ExternalCallRecord
from app.models.session import Session
from app.models.state_transition_event import StateTransitionEvent
from app.models.support_event import SupportEvent
from app.rules.session_lifecycle import (
    FLOW_STAGE_AI_EVALUATING,
    FLOW_STAGE_CAPTURING_INPUT,
    FLOW_STAGE_CONFIRMING_TEXT,
    FLOW_STAGE_SHOWING_FULL_SOLUTION,
    FLOW_STAGE_WAIT_INITIAL_CHOICE,
    FLOW_STAGE_WAIT_STUDENT_ACTION,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_NEED_HUMAN,
    STATUS_STOPPED_LIMIT,
    flow_stage_after_initial_choice,
)
from app.rules.teaching_cycle import (
    SUPPORT_TYPES,
    decide_evaluation,
    support_limit_for,
    support_limit_reached,
    update_coverage,
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

    def get_latest_valid_support(self, session_id: int) -> SupportEvent | None:
        statement = (
            select(SupportEvent)
            .where(SupportEvent.session_id == session_id, SupportEvent.status == "VALID")
            .order_by(SupportEvent.id.desc())
        )
        return self.database_session.scalars(statement).first()

    def get_student_timeline(self, session_id: int) -> list[dict[str, object]]:
        support_events = list(
            self.database_session.scalars(
                select(SupportEvent)
                .where(SupportEvent.session_id == session_id, SupportEvent.status == "VALID")
                .order_by(SupportEvent.created_at, SupportEvent.id)
            )
        )
        supports_by_evaluation_id = {
            support.evaluation_id: support
            for support in support_events
            if support.evaluation_id is not None
        }
        timeline: list[dict[str, object]] = []
        evaluations = self.database_session.scalars(
            select(AIEvaluation)
            .where(
                AIEvaluation.session_id == session_id,
                AIEvaluation.validation_status == "VALID",
            )
            .order_by(AIEvaluation.created_at, AIEvaluation.id)
        )
        for evaluation in evaluations:
            support = supports_by_evaluation_id.get(evaluation.id)
            timeline.append(
                {
                    "id": f"evaluation-{evaluation.id}",
                    "event_type": "EVALUATION",
                    "content": evaluation.feedback,
                    "correctness": evaluation.correctness,
                    "completeness": evaluation.completeness,
                    "action": (
                        support.support_type if support is not None else evaluation.next_action
                    ),
                    "created_at": evaluation.created_at,
                }
            )
        for support in support_events:
            if support.evaluation_id is None:
                timeline.append(
                    {
                        "id": f"support-{support.id}",
                        "event_type": "SUPPORT",
                        "content": support.content,
                        "correctness": None,
                        "completeness": None,
                        "action": support.support_type,
                        "created_at": support.created_at,
                    }
                )
        solution_transitions = self.database_session.scalars(
            select(StateTransitionEvent)
            .where(
                StateTransitionEvent.session_id == session_id,
                StateTransitionEvent.to_flow_stage == FLOW_STAGE_SHOWING_FULL_SOLUTION,
            )
            .order_by(StateTransitionEvent.created_at, StateTransitionEvent.id)
        )
        for transition in solution_transitions:
            timeline.append(
                {
                    "id": f"solution-{transition.id}",
                    "event_type": "FULL_SOLUTION",
                    "content": "已展示完整解析。",
                    "correctness": None,
                    "completeness": None,
                    "action": None,
                    "created_at": transition.created_at,
                }
            )
        human_transitions = self.database_session.scalars(
            select(StateTransitionEvent)
            .where(
                StateTransitionEvent.session_id == session_id,
                StateTransitionEvent.to_status == STATUS_NEED_HUMAN,
            )
            .order_by(StateTransitionEvent.created_at, StateTransitionEvent.id)
        )
        for transition in human_transitions:
            timeline.append(
                {
                    "id": f"human-{transition.id}",
                    "event_type": "NEED_HUMAN",
                    "content": student_need_human_message(transition.trigger_type),
                    "correctness": None,
                    "completeness": None,
                    "action": None,
                    "created_at": transition.created_at,
                }
            )
        return sorted(timeline, key=lambda item: (item["created_at"], str(item["id"])))

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
        call_type: str = "AI_EVALUATION",
        error_type: str | None = None,
        error_message: str | None = None,
        raw_response: str | None = None,
    ) -> None:
        self.database_session.add(
            ExternalCallRecord(
                session_id=session.id,
                call_type=call_type,
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
        settings: Settings,
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
        (
            session.covered_points_current_round,
            session.covered_points_all,
            session.no_progress_count,
        ) = update_coverage(
            covered_points=evaluation.covered_points,
            covered_points_current_round=session.covered_points_current_round,
            covered_points_all=session.covered_points_all,
            no_progress_count=session.no_progress_count,
        )
        decision = decide_evaluation(
            next_action=evaluation.next_action,
            no_progress_count=session.no_progress_count,
            settings=settings,
            solution_exposed=session.solution_exposed,
            round_number=session.round,
            support_count_total=session.support_count_total,
            need_human_reason=evaluation.need_human_reason,
        )
        if decision.next_status is not None:
            session.status = decision.next_status
        if decision.next_flow_stage is not None:
            session.flow_stage = decision.next_flow_stage
        if decision.completion_type is not None:
            session.completion_type = decision.completion_type
        if decision.need_human_reason is not None:
            session.need_human_reason = decision.need_human_reason
        if decision.action in SUPPORT_TYPES:
            self._apply_support(
                session=session,
                support_type=decision.action,
                content=evaluation.feedback,
                evaluation_id=saved_evaluation.id,
                settings=settings,
            )
        if session.status in {STATUS_COMPLETED, STATUS_NEED_HUMAN, STATUS_STOPPED_LIMIT}:
            session.finished_at = datetime.now(UTC)
        if session.flow_stage == FLOW_STAGE_AI_EVALUATING:
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

    def begin_support_generation(self, session: Session, trigger_type: str) -> Session:
        before_snapshot = session_snapshot(session)
        session.flow_stage = FLOW_STAGE_AI_EVALUATING
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type=trigger_type,
            before_snapshot=before_snapshot,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def resolve_support_limit(
        self, *, session: Session, settings: Settings, trigger_type: str
    ) -> Session | None:
        if not support_limit_reached(
            round_number=session.round,
            support_count_round=session.support_count_round,
            settings=settings,
        ):
            return None
        before_snapshot = session_snapshot(session)
        # 触发上限时不会发送局部支持，因此不会创建 SupportEvent。
        self._apply_support(
            session=session,
            support_type="GIVE_HINT",
            content="",
            evaluation_id=None,
            settings=settings,
        )
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type=trigger_type,
            before_snapshot=before_snapshot,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def record_generated_hint(
        self, *, session: Session, content: str, settings: Settings
    ) -> Session:
        before_snapshot = session_snapshot(session)
        self._apply_support(
            session=session,
            support_type="GIVE_HINT",
            content=content,
            evaluation_id=None,
            settings=settings,
        )
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="SEND_GENERATED_HINT",
            before_snapshot=before_snapshot,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def return_to_wait_student_action_after_support_failure(
        self, *, session: Session, trigger_type: str
    ) -> Session:
        before_snapshot = session_snapshot(session)
        session.flow_stage = FLOW_STAGE_WAIT_STUDENT_ACTION
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type=trigger_type,
            before_snapshot=before_snapshot,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def mark_support_schema_retry_exhausted(
        self, *, session: Session, need_human_reason: str
    ) -> Session:
        before_snapshot = session_snapshot(session)
        session.status = STATUS_NEED_HUMAN
        session.flow_stage = FLOW_STAGE_WAIT_STUDENT_ACTION
        session.need_human_reason = need_human_reason
        session.finished_at = datetime.now(UTC)
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="AI_SUPPORT_SCHEMA_RETRY_EXHAUSTED",
            before_snapshot=before_snapshot,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def continue_explaining(self, session: Session) -> Session:
        before_snapshot = session_snapshot(session)
        session.flow_stage = FLOW_STAGE_CAPTURING_INPUT
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="CONTINUE_EXPLAINING",
            before_snapshot=before_snapshot,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def appeal(self, *, session: Session, reason: str, evaluation_id: int) -> Session:
        before_snapshot = session_snapshot(session)
        session.status = STATUS_NEED_HUMAN
        session.flow_stage = FLOW_STAGE_WAIT_STUDENT_ACTION
        session.need_human_reason = f"学生申诉：{reason}"
        session.finished_at = datetime.now(UTC)
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="STUDENT_APPEAL",
            before_snapshot=before_snapshot,
            related_evaluation_id=evaluation_id,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def respond_to_first_solution(self, *, session: Session, understood: bool) -> Session:
        before_snapshot = session_snapshot(session)
        if understood:
            session.round = 2
            session.support_count_round = 0
            session.no_progress_count = 0
            session.covered_points_current_round = []
            session.flow_stage = FLOW_STAGE_CAPTURING_INPUT
            trigger_type = "UNDERSTOOD_FIRST_SOLUTION"
        else:
            session.status = STATUS_NEED_HUMAN
            session.flow_stage = FLOW_STAGE_WAIT_STUDENT_ACTION
            session.need_human_reason = "学生在第一轮完整解析后仍表示不会"
            session.finished_at = datetime.now(UTC)
            trigger_type = "DID_NOT_UNDERSTAND_FIRST_SOLUTION"
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type=trigger_type,
            before_snapshot=before_snapshot,
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

    def _apply_support(
        self,
        *,
        session: Session,
        support_type: str,
        content: str,
        evaluation_id: int | None,
        settings: Settings,
    ) -> None:
        if support_type not in SUPPORT_TYPES:
            raise ValueError(f"不支持的计数支持类型：{support_type}")
        if support_limit_reached(
            round_number=session.round,
            support_count_round=session.support_count_round,
            settings=settings,
        ):
            session.support_count_round = support_limit_for(
                round_number=session.round, settings=settings
            )
            session.solution_exposed = True
            if session.round == 1:
                session.flow_stage = FLOW_STAGE_SHOWING_FULL_SOLUTION
            else:
                session.status = STATUS_STOPPED_LIMIT
                session.flow_stage = FLOW_STAGE_SHOWING_FULL_SOLUTION
                session.finished_at = datetime.now(UTC)
            return
        self.database_session.add(
            SupportEvent(
                session_id=session.id,
                evaluation_id=evaluation_id,
                support_type=support_type,
                round=session.round,
                status="VALID",
                content=content,
            )
        )
        session.support_count_round += 1
        session.support_count_total += 1
        session.flow_stage = FLOW_STAGE_WAIT_STUDENT_ACTION


def student_need_human_message(trigger_type: str) -> str:
    if trigger_type == "STUDENT_APPEAL":
        return "已提交不同意 AI 判断的申诉，已转人工帮助。"
    if trigger_type == "DID_NOT_UNDERSTAND_FIRST_SOLUTION":
        return "你在阅读完整解析后仍表示不会，已转人工帮助。"
    if trigger_type == "APPLY_AI_EVALUATION":
        return "暂无法可靠判断，已转人工帮助。"
    return "当前无法自动继续，已转人工帮助。"
