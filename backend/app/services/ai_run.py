"""Cancellation boundary for one student-triggered AI operation."""

import asyncio
from contextvars import ContextVar
from datetime import UTC, datetime
from threading import Event, Lock
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.orm import Session as DatabaseSession

from app.models.ai_evaluation import AIEvaluation
from app.models.ai_run import AIRun
from app.models.explanation_attempt import ExplanationAttempt
from app.models.first_explanation_grading import FirstExplanationGrading
from app.models.mastery_check import MasteryCheck
from app.models.session import Session
from app.models.state_transition_event import StateTransitionEvent
from app.models.student_submission import StudentSubmission
from app.models.support_event import SupportEvent
from app.repositories.sessions import session_snapshot


class AIRunCancelled(RuntimeError):
    pass


class RunHandle:
    def __init__(self) -> None:
        self.cancelled = Event()
        self._lock = Lock()
        self._tasks: set[tuple[asyncio.AbstractEventLoop, asyncio.Task]] = set()

    async def _post(self, url: str, *, headers: dict, body: dict, timeout: float) -> httpx.Response:
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        with self._lock:
            if self.cancelled.is_set():
                raise AIRunCancelled("AI 运行已取消")
            self._tasks.add((loop, task))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                return await client.post(url, headers=headers, json=body)
        except asyncio.CancelledError as error:
            raise AIRunCancelled("AI 运行已取消") from error
        finally:
            with self._lock:
                self._tasks.discard((loop, task))

    def post(self, url: str, *, headers: dict, body: dict, timeout: float) -> httpx.Response:
        self.check()
        response = asyncio.run(self._post(url, headers=headers, body=body, timeout=timeout))
        self.check()
        return response

    def cancel(self) -> None:
        self.cancelled.set()
        with self._lock:
            tasks = list(self._tasks)
        for loop, task in tasks:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass

    def check(self) -> None:
        if self.cancelled.is_set():
            raise AIRunCancelled("AI 运行已取消")


current_run: ContextVar[RunHandle | None] = ContextVar("current_ai_run", default=None)


def _checkpoint(db: DatabaseSession, model, session_id: int) -> int:
    return db.scalar(select(func.max(model.id)).where(model.session_id == session_id)) or 0


def begin_run(db: DatabaseSession, session: Session, run_id: str | None, runtime) -> str:
    expected_version = session.version
    if run_id is None:
        run_id = str(uuid4())
    else:
        run_id = str(UUID(run_id))
    locked = db.scalar(
        select(Session).where(Session.id == session.id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or locked.version != expected_version:
        raise ValueError("会话版本已变化，请刷新后重试")
    existing = db.scalar(select(AIRun).where(AIRun.id == run_id).with_for_update())
    if existing is not None:
        if existing.session_id == session.id and existing.status == "CANCELLED":
            raise AIRunCancelled("AI 运行已取消")
        raise ValueError("AI 运行标识已使用")
    previous_support = db.scalar(
        select(SupportEvent).where(SupportEvent.session_id == session.id)
        .order_by(SupportEvent.id.desc()).limit(1)
    )
    previous_mastery = db.scalar(
        select(MasteryCheck).where(MasteryCheck.session_id == session.id)
        .order_by(MasteryCheck.id.desc()).limit(1)
    )
    previous_grading = db.scalar(
        select(FirstExplanationGrading).where(FirstExplanationGrading.session_id == session.id)
        .order_by(FirstExplanationGrading.id.desc()).limit(1)
    )
    checkpoints = {
        "evaluation": _checkpoint(db, AIEvaluation, session.id),
        "support": _checkpoint(db, SupportEvent, session.id),
        "mastery": _checkpoint(db, MasteryCheck, session.id),
        "grading": _checkpoint(db, FirstExplanationGrading, session.id),
        "submission": _checkpoint(db, StudentSubmission, session.id),
        "attempt": _checkpoint(db, ExplanationAttempt, session.id),
        "transition": _checkpoint(db, StateTransitionEvent, session.id),
        "previousGrading": None if previous_grading is None else {
            "id": previous_grading.id,
            "status": previous_grading.status,
            "errorMessage": previous_grading.error_message,
        },
        "previousSupport": None if previous_support is None else {
            "id": previous_support.id,
            "guidedAnswers": previous_support.guided_answers,
            "followUpContent": previous_support.follow_up_content,
            "status": previous_support.status,
        },
        "previousMastery": None if previous_mastery is None else {
            "id": previous_mastery.id,
            "answers": previous_mastery.answers,
            "results": previous_mastery.results,
            "outcome": previous_mastery.outcome,
            "completedAt": previous_mastery.completed_at.isoformat()
            if previous_mastery.completed_at else None,
        },
    }
    snapshot = session_snapshot(locked)
    snapshot["lastSupportDraft"] = locked.last_support_draft
    snapshot["finishedAt"] = locked.finished_at.isoformat() if locked.finished_at else None
    db.add(AIRun(
        id=run_id, session_id=session.id, base_version=session.version,
        status="ACTIVE", snapshot=snapshot, checkpoints=checkpoints,
    ))
    locked.active_run_id = run_id
    handle = runtime.run_handles.setdefault(run_id, RunHandle())
    try:
        db.commit()
    except Exception:
        runtime.run_handles.pop(run_id, None)
        raise
    db.info["ai_run"] = (session.id, run_id)
    handle.check()
    current_run.set(handle)
    return run_id


def bind_run(db: DatabaseSession, session_id: int, run_id: str, runtime) -> RunHandle:
    active = db.scalar(select(Session.active_run_id).where(Session.id == session_id))
    if active != run_id:
        raise AIRunCancelled("AI 运行已取消或结束")
    db.info["ai_run"] = (session_id, run_id)
    handle = runtime.run_handles.setdefault(run_id, RunHandle())
    current_run.set(handle)
    return handle


def finish_run(db: DatabaseSession, session_id: int, run_id: str, runtime) -> None:
    session = db.scalar(select(Session).where(Session.id == session_id).with_for_update())
    if session is None or session.active_run_id != run_id:
        return
    record = db.scalar(select(AIRun).where(AIRun.id == run_id).with_for_update())
    if record is not None:
        record.status = "COMPLETED"
    session.active_run_id = None
    db.commit()
    runtime.run_handles.pop(run_id, None)


def cancel_run(db: DatabaseSession, session: Session, run_id: str, runtime) -> Session:
    locked = db.scalar(
        select(Session).where(Session.id == session.id).with_for_update()
        .execution_options(populate_existing=True)
    )
    record = db.scalar(select(AIRun).where(AIRun.id == run_id).with_for_update())
    if (
        locked is None or locked.active_run_id != run_id
        or record is None or record.status != "ACTIVE"
    ):
        raise AIRunCancelled("当前运行不存在或已结束")
    handle = runtime.run_handles.get(run_id)
    if handle is not None:
        handle.cancel()
    snapshot = record.snapshot
    checkpoints = record.checkpoints
    record.status = "CANCELLED"
    record.cancelled_at = datetime.now(UTC)
    locked.active_run_id = None
    for field, key in (
        ("status", "status"), ("flow_stage", "flowStage"), ("round", "round"),
        ("support_count_round", "supportCountRound"),
        ("support_count_total", "supportCountTotal"),
        ("no_progress_count", "noProgressCount"),
        ("no_progress_help_request_count", "noProgressHelpRequestCount"),
        ("solution_exposed", "solutionExposed"),
        ("completion_type", "completionType"),
        ("need_human_reason", "needHumanReason"),
        ("last_support_draft", "lastSupportDraft"),
        ("current_step_id", "currentStepId"),
        ("paused_from_stage", "pausedFromStage"),
    ):
        setattr(locked, field, snapshot[key])
    locked.current_draft = snapshot["currentDraft"]
    locked.finished_at = (
        datetime.fromisoformat(snapshot["finishedAt"]) if snapshot["finishedAt"] else None
    )
    locked.version += 1

    for evaluation in db.scalars(select(AIEvaluation).where(
        AIEvaluation.session_id == session.id, AIEvaluation.id > checkpoints["evaluation"]
    )):
        evaluation.validation_status = "CANCELLED"
    for support in db.scalars(select(SupportEvent).where(
        SupportEvent.session_id == session.id, SupportEvent.id > checkpoints["support"]
    )):
        support.status = "CANCELLED"
    for grading in db.scalars(select(FirstExplanationGrading).where(
        FirstExplanationGrading.session_id == session.id,
        FirstExplanationGrading.id > checkpoints["grading"],
    )):
        grading.status = "CANCELLED"
        grading.evaluation_status = "CANCELLED"
        grading.report = None
        grading.correctness_score = None
        grading.completeness_score = None
        grading.total_score = None
    previous_grading = checkpoints["previousGrading"]
    if previous_grading:
        grading = db.get(FirstExplanationGrading, previous_grading["id"])
        grading.status = previous_grading["status"]
        grading.error_message = previous_grading["errorMessage"]
    db.execute(delete(MasteryCheck).where(
        MasteryCheck.session_id == session.id, MasteryCheck.id > checkpoints["mastery"]
    ))
    previous_support = checkpoints["previousSupport"]
    if previous_support:
        support = db.get(SupportEvent, previous_support["id"])
        support.guided_answers = previous_support["guidedAnswers"]
        support.follow_up_content = previous_support["followUpContent"]
        support.status = previous_support["status"]
    previous_mastery = checkpoints["previousMastery"]
    if previous_mastery:
        mastery = db.get(MasteryCheck, previous_mastery["id"])
        mastery.answers = previous_mastery["answers"]
        mastery.results = previous_mastery["results"]
        mastery.outcome = previous_mastery["outcome"]
        mastery.completed_at = (
            datetime.fromisoformat(previous_mastery["completedAt"])
            if previous_mastery["completedAt"] else None
        )
    for submission in db.scalars(select(StudentSubmission).where(
        StudentSubmission.session_id == session.id,
        StudentSubmission.id > checkpoints["submission"],
    )):
        submission.context = {**submission.context, "cancelledRunId": run_id}
    for attempt in db.scalars(select(ExplanationAttempt).where(
        ExplanationAttempt.session_id == session.id,
        ExplanationAttempt.id > checkpoints["attempt"],
    )):
        attempt.cancelled_run_id = run_id
    for transition in db.scalars(select(StateTransitionEvent).where(
        StateTransitionEvent.session_id == session.id,
        StateTransitionEvent.id > checkpoints["transition"],
    )):
        transition.cancelled_run_id = run_id
    from app.repositories.sessions import SessionRepository

    SessionRepository(db)._record_transition(
        session=locked, trigger_type="CANCEL_AI_RUN", before_snapshot=snapshot,
    )
    db.commit()
    runtime.run_handles.pop(run_id, None)
    db.refresh(locked)
    return locked


def cancel_or_reserve_run(db: DatabaseSession, session: Session, run_id: str, runtime) -> Session:
    run_id = str(UUID(run_id))
    locked = db.scalar(
        select(Session).where(Session.id == session.id).with_for_update()
        .execution_options(populate_existing=True)
    )
    existing = db.scalar(select(AIRun).where(AIRun.id == run_id).with_for_update())
    if existing is not None:
        if existing.session_id != session.id:
            raise AIRunCancelled("运行不属于当前会话")
        return cancel_run(db, session, run_id, runtime)
    if locked.active_run_id is not None:
        raise AIRunCancelled("当前运行与取消目标不匹配")
    snapshot = session_snapshot(locked)
    snapshot["finishedAt"] = locked.finished_at.isoformat() if locked.finished_at else None
    db.add(AIRun(
        id=run_id, session_id=session.id, base_version=session.version,
        status="CANCELLED", snapshot=snapshot, checkpoints={},
        cancelled_at=datetime.now(UTC),
    ))
    db.commit()
    return locked


@sqlalchemy_event.listens_for(DatabaseSession, "before_commit")
def _reject_cancelled_run_commit(db: DatabaseSession) -> None:
    binding = db.info.get("ai_run")
    if binding is None:
        return
    session_id, run_id = binding
    active = db.connection().execute(
        select(Session.active_run_id).where(Session.id == session_id).with_for_update()
    ).scalar_one_or_none()
    if active != run_id:
        raise AIRunCancelled("AI 运行已取消或被新操作取代")
