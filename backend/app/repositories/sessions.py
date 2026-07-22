from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from app.core.config import Settings
from app.core.logging import current_request_id
from app.models.ai_evaluation import AIEvaluation
from app.models.audio_file import AudioFile
from app.models.explanation_attempt import ExplanationAttempt
from app.models.external_call_record import ExternalCallRecord
from app.models.session import Session
from app.models.state_transition_event import StateTransitionEvent
from app.models.student_submission import StudentSubmission
from app.models.support_event import SupportEvent
from app.rules.session_lifecycle import (
    FLOW_STAGE_AI_EVALUATING,
    FLOW_STAGE_CAPTURING_INPUT,
    FLOW_STAGE_CONFIRMING_TEXT,
    FLOW_STAGE_SHOWING_FULL_SOLUTION,
    FLOW_STAGE_WAIT_GUIDED_ANSWERS,
    FLOW_STAGE_WAIT_INITIAL_CHOICE,
    FLOW_STAGE_WAIT_STUDENT_ACTION,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_NEED_HUMAN,
    STATUS_PAUSED,
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
from app.schemas.support import GuidedAnswer, GuidedQuestion
from app.services.audio_storage import AudioCapture, AudioStorage


def session_snapshot(session: Session) -> dict[str, object]:
    return {
        "status": session.status,
        "flowStage": session.flow_stage,
        "round": session.round,
        "supportCountRound": session.support_count_round,
        "supportCountTotal": session.support_count_total,
        "noProgressCount": session.no_progress_count,
        "noProgressHelpRequestCount": session.no_progress_help_request_count,
        "solutionExposed": session.solution_exposed,
        "completionType": session.completion_type,
        "needHumanReason": session.need_human_reason,
        "coveredPointsCurrentRound": session.covered_points_current_round,
        "coveredPointsAll": session.covered_points_all,
        "currentDraft": session.current_draft,
        "version": session.version,
        "pausedFromStage": session.paused_from_stage,
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
            no_progress_help_request_count=0,
            solution_exposed=False,
            covered_points_current_round=[],
            covered_points_all=[],
            current_draft="",
            last_support_draft="",
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

    def get_state_events(self, session_id: int) -> list[StateTransitionEvent]:
        return list(
            self.database_session.scalars(
                select(StateTransitionEvent)
                .where(StateTransitionEvent.session_id == session_id)
                .order_by(StateTransitionEvent.created_at, StateTransitionEvent.id)
            )
        )

    def get_external_calls(self, session_id: int) -> list[ExternalCallRecord]:
        return list(
            self.database_session.scalars(
                select(ExternalCallRecord)
                .where(ExternalCallRecord.session_id == session_id)
                .order_by(ExternalCallRecord.created_at, ExternalCallRecord.id)
            )
        )

    def get_external_call_errors(self, session_id: int) -> list[ExternalCallRecord]:
        return list(
            self.database_session.scalars(
                select(ExternalCallRecord)
                .where(
                    ExternalCallRecord.session_id == session_id,
                    ExternalCallRecord.error_type.is_not(None),
                )
                .order_by(ExternalCallRecord.created_at, ExternalCallRecord.id)
            )
        )

    def pause(self, session: Session) -> Session:
        before_snapshot = session_snapshot(session)
        session.paused_from_stage = session.flow_stage
        session.status = STATUS_PAUSED
        session.version += 1
        self._record_transition(
            session=session, trigger_type="PAUSE_SESSION", before_snapshot=before_snapshot
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def resume(self, session: Session) -> Session:
        before_snapshot = session_snapshot(session)
        if not session.paused_from_stage:
            raise ValueError(f"会话 {session.id} 缺少暂停前流程阶段")
        session.status = STATUS_IN_PROGRESS
        session.flow_stage = session.paused_from_stage
        session.paused_from_stage = None
        session.version += 1
        self._record_transition(
            session=session, trigger_type="RESUME_SESSION", before_snapshot=before_snapshot
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def get_latest_attempt(self, session_id: int) -> ExplanationAttempt | None:
        statement = (
            select(ExplanationAttempt)
            .where(ExplanationAttempt.session_id == session_id)
            .order_by(ExplanationAttempt.id.desc())
        )
        return self.database_session.scalars(statement).first()

    def get_pending_voice_attempt(self, session_id: int) -> ExplanationAttempt | None:
        statement = (
            select(ExplanationAttempt)
            .where(
                ExplanationAttempt.session_id == session_id,
                ExplanationAttempt.input_mode == "VOICE",
                ExplanationAttempt.confirmed_text.is_(None),
            )
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
            .where(SupportEvent.session_id == session_id)
            .order_by(SupportEvent.id.desc())
        )
        return self.database_session.scalars(statement).first()

    def get_student_timeline(self, session_id: int) -> list[dict[str, object]]:
        student_submissions = list(
            self.database_session.scalars(
                select(StudentSubmission)
                .where(StudentSubmission.session_id == session_id)
                .order_by(StudentSubmission.created_at, StudentSubmission.id)
            )
        )
        support_events = list(
            self.database_session.scalars(
                select(SupportEvent)
                .where(SupportEvent.session_id == session_id)
                .order_by(SupportEvent.created_at, SupportEvent.id)
            )
        )
        supports_by_evaluation_id = {
            support.evaluation_id: support
            for support in support_events
            if support.evaluation_id is not None
        }
        guided_answer_submissions_by_support_id = {
            int(submission.context["supportEventId"]): submission
            for submission in student_submissions
            if (
                submission.submission_type == "GUIDED_ANSWER"
                and isinstance(submission.context, dict)
                and "supportEventId" in submission.context
            )
        }
        timeline: list[dict[str, object]] = []
        for submission in student_submissions:
            timeline.append(
                {
                    "id": f"submission-{submission.id}",
                    "event_type": "SUBMISSION",
                    "speaker": "STUDENT",
                    "submission_type": submission.submission_type,
                    "content": submission.content,
                    "correctness": None,
                    "completeness": None,
                    "action": None,
                    "created_at": submission.created_at,
                }
            )
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
                    "speaker": "AI",
                    "submission_type": None,
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
                        "speaker": "AI",
                        "submission_type": None,
                        "content": support.content,
                        "correctness": None,
                        "completeness": None,
                        "action": support.support_type,
                        "created_at": support.created_at,
                    }
                )
                if support.follow_up_content:
                    answer_submission = guided_answer_submissions_by_support_id.get(support.id)
                    timeline.append(
                        {
                            "id": f"support-follow-up-{support.id}",
                            "event_type": "SUPPORT",
                            "speaker": "AI",
                            "submission_type": None,
                            "content": support.follow_up_content,
                            "correctness": None,
                            "completeness": None,
                            "action": support.support_type,
                            "created_at": (
                                answer_submission.created_at
                                if answer_submission is not None
                                else support.created_at
                            ),
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
                    "speaker": "SYSTEM",
                    "submission_type": None,
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
                    "speaker": "SYSTEM",
                    "submission_type": None,
                    "content": student_need_human_message(transition.trigger_type),
                    "correctness": None,
                    "completeness": None,
                    "action": None,
                    "created_at": transition.created_at,
                }
            )
        return sorted(timeline, key=_timeline_sort_key)

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
        self._record_student_submission(
            session=session,
            submission_type="SELF_EXPLANATION",
            content=confirmed_text,
            context={"inputMode": "TEXT", "attemptId": attempt.id, "round": session.round},
        )
        session.current_draft = confirmed_text
        session.last_support_draft = confirmed_text
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

    def complete_voice_transcription(
        self,
        *,
        session: Session,
        capture: AudioCapture,
        audio_storage: AudioStorage,
        asr_transcript: str,
    ) -> tuple[Session, ExplanationAttempt]:
        before_snapshot = session_snapshot(session)
        audio_file = AudioFile(
            session_id=session.id,
            relative_path="",
            content_type=audio_storage.content_type,
            size_bytes=capture.size_bytes,
            sha256=capture.sha256.hexdigest(),
        )
        self.database_session.add(audio_file)
        self.database_session.flush()
        relative_path: str | None = None
        try:
            relative_path = audio_storage.finalize_capture(
                capture, session_id=session.id, audio_file_id=audio_file.id
            )
            audio_file.relative_path = relative_path
            attempt = ExplanationAttempt(
                session_id=session.id,
                round=session.round,
                input_mode="VOICE",
                audio_file_id=audio_file.id,
                asr_transcript=asr_transcript,
                confirmed_text=None,
                confirmed_at=None,
            )
            self.database_session.add(attempt)
            self.database_session.flush()
            session.flow_stage = FLOW_STAGE_CONFIRMING_TEXT
            session.version += 1
            self._record_transition(
                session=session,
                trigger_type="COMPLETE_VOICE_TRANSCRIPTION",
                before_snapshot=before_snapshot,
                related_attempt_id=attempt.id,
            )
            self.database_session.commit()
        except Exception:
            self.database_session.rollback()
            if relative_path is not None:
                audio_storage.delete_relative_path(relative_path)
            else:
                capture.delete()
            raise
        self.database_session.refresh(session)
        self.database_session.refresh(attempt)
        return session, attempt

    def confirm_voice_attempt(
        self, *, session: Session, attempt: ExplanationAttempt, confirmed_text: str
    ) -> tuple[Session, ExplanationAttempt]:
        before_snapshot = session_snapshot(session)
        attempt.confirmed_text = confirmed_text
        attempt.confirmed_at = datetime.now(UTC)
        self._record_student_submission(
            session=session,
            submission_type="SELF_EXPLANATION",
            content=confirmed_text,
            context={"inputMode": "VOICE", "attemptId": attempt.id, "round": session.round},
        )
        session.current_draft = confirmed_text
        session.last_support_draft = confirmed_text
        session.flow_stage = FLOW_STAGE_AI_EVALUATING
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="CONFIRM_VOICE_TRANSCRIPT",
            before_snapshot=before_snapshot,
            related_attempt_id=attempt.id,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        self.database_session.refresh(attempt)
        return session, attempt

    def record_asr_stream_failure(self, *, session: Session, trigger_type: str) -> Session:
        before_snapshot = session_snapshot(session)
        self._record_transition(
            session=session,
            trigger_type=trigger_type,
            before_snapshot=before_snapshot,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

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
        request_id: str | None = None,
    ) -> None:
        self.database_session.add(
            ExternalCallRecord(
                session_id=session.id,
                request_id=request_id or current_request_id(),
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
        new_points = set(evaluation.covered_points) - set(session.covered_points_current_round)
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
        if new_points:
            session.no_progress_help_request_count = 0
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

    def record_help_progress(
        self,
        *,
        session: Session,
        main_draft: str,
        covered_points: list[str],
        settings: Settings,
    ) -> bool:
        """记录本次求助前的草稿进展，并返回是否应给出当前步骤答案。"""
        before_snapshot = session_snapshot(session)
        normalized_draft = _normalize_draft(main_draft)
        previous_draft = _normalize_draft(session.last_support_draft)
        new_points: set[str] = set()
        session.current_draft = main_draft
        if normalized_draft and normalized_draft != previous_draft:
            new_points = set(covered_points) - set(session.covered_points_current_round)
            (
                session.covered_points_current_round,
                session.covered_points_all,
                session.no_progress_count,
            ) = update_coverage(
                covered_points=covered_points,
                covered_points_current_round=session.covered_points_current_round,
                covered_points_all=session.covered_points_all,
                no_progress_count=session.no_progress_count,
            )
        else:
            session.no_progress_count += 1
        session.last_support_draft = main_draft
        if new_points:
            session.no_progress_help_request_count = 0
        else:
            session.no_progress_help_request_count += 1
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="ASSESS_HELP_PROGRESS",
            before_snapshot=before_snapshot,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session.no_progress_help_request_count > settings.guided_question_request_limit

    def record_support_submission(
        self,
        *,
        session: Session,
        main_draft: str,
        doubt_text: str | None,
    ) -> None:
        self._record_support_submission(
            session=session,
            main_draft=main_draft,
            doubt_text=doubt_text,
        )

    def record_guided_questions(
        self,
        *,
        session: Session,
        main_draft: str,
        doubt_text: str | None,
        content: str,
        questions: list[GuidedQuestion],
        settings: Settings,
    ) -> Session:
        limited_session = self.resolve_support_limit(
            session=session,
            settings=settings,
            trigger_type="SUPPORT_LIMIT_REACHED",
        )
        if limited_session is not None:
            return limited_session
        before_snapshot = session_snapshot(session)
        self.database_session.add(
            SupportEvent(
                session_id=session.id,
                evaluation_id=None,
                support_type="GIVE_HINT",
                round=session.round,
                status="VALID",
                content=content,
                support_kind="GUIDED_QUESTIONS",
                main_draft=main_draft,
                doubt_text=doubt_text,
                guided_questions=[item.model_dump() for item in questions],
                guided_answers=None,
                follow_up_content=None,
            )
        )
        session.support_count_round += 1
        session.support_count_total += 1
        session.flow_stage = FLOW_STAGE_WAIT_GUIDED_ANSWERS
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="SEND_GUIDED_QUESTIONS",
            before_snapshot=before_snapshot,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def record_direct_help(
        self,
        *,
        session: Session,
        main_draft: str,
        doubt_text: str | None,
        content: str,
        support_kind: str,
        settings: Settings,
    ) -> Session:
        limited_session = self.resolve_support_limit(
            session=session,
            settings=settings,
            trigger_type="SUPPORT_LIMIT_REACHED",
        )
        if limited_session is not None:
            return limited_session
        before_snapshot = session_snapshot(session)
        self.database_session.add(
            SupportEvent(
                session_id=session.id,
                evaluation_id=None,
                support_type="GIVE_HINT",
                round=session.round,
                status="VALID",
                content=content,
                support_kind=support_kind,
                main_draft=main_draft,
                doubt_text=doubt_text,
                guided_questions=None,
                guided_answers=None,
                follow_up_content=None,
            )
        )
        session.current_draft = main_draft
        session.support_count_round += 1
        session.support_count_total += 1
        session.flow_stage = FLOW_STAGE_WAIT_STUDENT_ACTION
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="SEND_DIRECT_HELP",
            before_snapshot=before_snapshot,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def record_full_solution_refusal(
        self,
        *,
        session: Session,
        main_draft: str,
        doubt_text: str | None,
        content: str,
    ) -> Session:
        before_snapshot = session_snapshot(session)
        self.database_session.add(
            SupportEvent(
                session_id=session.id,
                evaluation_id=None,
                support_type="GIVE_HINT",
                round=session.round,
                status="REFUSED",
                content=content,
                support_kind="SIMPLE_DOUBT",
                main_draft=main_draft,
                doubt_text=doubt_text,
                guided_questions=None,
                guided_answers=None,
                follow_up_content=None,
            )
        )
        session.current_draft = main_draft
        session.flow_stage = FLOW_STAGE_WAIT_STUDENT_ACTION
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="REFUSE_FULL_SOLUTION_REQUEST",
            before_snapshot=before_snapshot,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def record_guided_answers(
        self,
        *,
        session: Session,
        support_event: SupportEvent,
        answers: list[GuidedAnswer],
        follow_up_content: str,
    ) -> Session:
        before_snapshot = session_snapshot(session)
        self._record_student_submission(
            session=session,
            submission_type="GUIDED_ANSWER",
            content=_format_guided_answers_for_timeline(
                support_event.guided_questions or [], answers
            ),
            context={"supportEventId": support_event.id, "round": session.round},
        )
        support_event.guided_answers = [item.model_dump() for item in answers]
        support_event.follow_up_content = follow_up_content
        session.flow_stage = FLOW_STAGE_WAIT_STUDENT_ACTION
        session.version += 1
        self._record_transition(
            session=session,
            trigger_type="SUBMIT_GUIDED_ANSWERS",
            before_snapshot=before_snapshot,
        )
        self.database_session.commit()
        self.database_session.refresh(session)
        return session

    def get_pending_guided_support(self, session_id: int) -> SupportEvent | None:
        statement = (
            select(SupportEvent)
            .where(
                SupportEvent.session_id == session_id,
                SupportEvent.support_kind == "GUIDED_QUESTIONS",
            )
            .order_by(SupportEvent.id.desc())
        )
        for support_event in self.database_session.scalars(statement):
            if support_event.guided_answers is None:
                return support_event
        return None

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
        self._record_student_submission(
            session=session,
            submission_type="APPEAL",
            content=reason,
            context={"evaluationId": evaluation_id, "round": session.round},
        )
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
            session.no_progress_help_request_count = 0
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

    def _record_student_submission(
        self,
        *,
        session: Session,
        submission_type: str,
        content: str,
        context: dict[str, object] | None = None,
    ) -> None:
        self.database_session.add(
            StudentSubmission(
                session_id=session.id,
                submission_type=submission_type,
                content=content,
                context=context or {},
            )
        )

    def _record_support_submission(
        self,
        *,
        session: Session,
        main_draft: str,
        doubt_text: str | None,
    ) -> None:
        if doubt_text is not None:
            self._record_student_submission(
                session=session,
                submission_type="DOUBT",
                content=doubt_text,
                context={"mainDraft": main_draft, "round": session.round},
            )
            return
        self._record_student_submission(
            session=session,
            submission_type="SUPPORT_REQUEST",
            content=main_draft,
            context={"round": session.round},
        )

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
                request_id=current_request_id(),
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
                support_kind="EVALUATION",
                main_draft=session.current_draft,
                doubt_text=None,
                guided_questions=None,
                guided_answers=None,
                follow_up_content=None,
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


def _format_guided_answers_for_timeline(
    guided_questions: list[dict[str, str]], answers: list[GuidedAnswer]
) -> str:
    question_by_id = {
        str(question["id"]): str(question["question"])
        for question in guided_questions
        if "id" in question and "question" in question
    }
    answer_blocks = []
    for index, answer in enumerate(answers, start=1):
        question = question_by_id.get(answer.question_id, f"第 {index} 个子问题")
        answer_blocks.append(f"{question}\n答：{answer.answer}")
    return "\n\n".join(answer_blocks)


def _timeline_sort_key(item: dict[str, object]) -> tuple[object, int, str]:
    event_type = str(item["event_type"])
    submission_type = str(item.get("submission_type"))
    if event_type == "SUBMISSION" and submission_type == "SELF_EXPLANATION":
        event_order = 0
    elif event_type == "EVALUATION":
        event_order = 1
    elif event_type == "SUBMISSION":
        event_order = 2
    elif event_type == "SUPPORT":
        event_order = 3
    else:
        event_order = 4
    return (
        item["created_at"],
        event_order,
        str(item["id"]),
    )


def _normalize_draft(value: str) -> str:
    return "\n".join(line.strip() for line in value.replace("\r\n", "\n").split("\n")).strip()
