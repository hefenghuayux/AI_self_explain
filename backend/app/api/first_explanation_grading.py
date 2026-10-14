import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.sessions import begin_ai_run, get_session_or_404, to_session_response
from app.core.auth import CurrentUser, DatabaseSession
from app.models.explanation_attempt import ExplanationAttempt
from app.models.first_explanation_grading import FirstExplanationGrading
from app.repositories.sessions import SessionRepository, SessionVersionConflict
from app.rules.session_lifecycle import FLOW_STAGE_CAPTURING_INPUT, STATUS_IN_PROGRESS
from app.schemas.first_explanation_grading import (
    FirstExplanationGradingResponse,
    FirstExplanationSubmissionResponse,
)
from app.schemas.session_step import StepAttemptInput
from app.services.context_runtime import preflight_submission
from app.services.first_explanation_grading import (
    create_grading_record,
    run_grading_only,
    run_parallel_tasks,
    to_grading_response,
)

router = APIRouter(prefix="/sessions", tags=["first-explanation-grading"])
logger = logging.getLogger(__name__)


def _record_for(db, session_id: int, attempt_id: int | None = None):
    query = select(FirstExplanationGrading).where(
        FirstExplanationGrading.session_id == session_id,
        FirstExplanationGrading.status != "CANCELLED",
    )
    if attempt_id is not None:
        query = query.where(FirstExplanationGrading.attempt_id == attempt_id)
    return db.scalar(query.order_by(FirstExplanationGrading.id.desc()))


def _schedule_parallel_tasks(
    *, request: Request, session_id: int, attempt_id: int, grading_id: int, run_id: str
):
    async def run() -> None:
        try:
            await asyncio.to_thread(
                run_parallel_tasks,
                settings=request.app.state.settings,
                http_client=request.app.state.ai_http_client,
                database_session_factory=request.app.state.database_session_factory,
                session_id=session_id,
                attempt_id=attempt_id,
                grading_id=grading_id,
                run_id=run_id,
                runtime=request.app.state.context_runtime,
                teacher_speech_service=request.app.state.teacher_speech_service,
                prewarm_speech=request.headers.get("X-Teacher-Speech-Prewarm") == "true",
            )
        except Exception:
            logger.exception("首次自讲后台任务未完成 session=%s", session_id)
            if getattr(request.state, "stream_managed", False):
                raise

    return asyncio.create_task(run())


def _schedule_grading_retry(
    *, request: Request, session_id: int, attempt_id: int, grading_id: int, run_id: str
):
    async def run() -> None:
        try:
            await asyncio.to_thread(
                run_grading_only,
                settings=request.app.state.settings,
                http_client=request.app.state.ai_http_client,
                database_session_factory=request.app.state.database_session_factory,
                session_id=session_id,
                attempt_id=attempt_id,
                grading_id=grading_id,
                run_id=run_id,
                runtime=request.app.state.context_runtime,
            )
        except Exception:
            logger.exception("首次自讲评分重试未完成 session=%s", session_id)
            if getattr(request.state, "stream_managed", False):
                raise

    return asyncio.create_task(run())


@router.post(
    "/{session_id}/graded-step-attempts",
    response_model=FirstExplanationSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_graded_step_attempt(
    session_id: int,
    attempt_input: StepAttemptInput,
    request: Request,
    database_session: DatabaseSession,
    current_user: CurrentUser,
):
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    if session.status != STATUS_IN_PROGRESS or session.flow_stage != FLOW_STAGE_CAPTURING_INPUT:
        raise HTTPException(status_code=409, detail="当前会话不能提交首次评分")
    if _record_for(database_session, session_id) is not None:
        raise HTTPException(status_code=409, detail="首次正式自讲评分已经提交")
    if database_session.scalar(
        select(ExplanationAttempt.id).where(
            ExplanationAttempt.session_id == session_id,
            ~ExplanationAttempt.id.in_(
                select(FirstExplanationGrading.attempt_id).where(
                    FirstExplanationGrading.session_id == session_id,
                    FirstExplanationGrading.status == "CANCELLED",
                )
            ),
        )
        .limit(1)
    ) is not None:
        raise HTTPException(status_code=409, detail="首次正式自讲已经提交")
    from app.api.sessions import validate_version

    validate_version(session, attempt_input.version)
    current_step_id = session.current_step_id
    if current_step_id is None:
        raise HTTPException(status_code=409, detail="当前自讲步骤不存在")
    try:
        explanation, projection = repository.build_step_snapshot(
            session=session, current_step_id=current_step_id,
            current_step_content=attempt_input.current_step_content,
        )
        begin_ai_run(database_session, session, request)
        preflight_submission(
            database_session, session, request.app.state.settings,
            attempt=ExplanationAttempt(confirmed_text=projection, student_explanation=explanation),
        )
        session, attempt = repository.submit_step_attempt(
            session=session, current_step_id=current_step_id,
            current_step_content=attempt_input.current_step_content,
            expected_version=attempt_input.version,
        )
    except SessionVersionConflict as error:
        raise HTTPException(status_code=409, detail="会话版本已变化，请刷新后重试") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    grading = create_grading_record(database_session, session, attempt)
    task = _schedule_parallel_tasks(
        request=request, session_id=session.id, attempt_id=attempt.id,
        grading_id=grading.id, run_id=request.state.ai_run_id,
    )
    if getattr(request.state, "stream_managed", False):
        from app.services.ai_stream import current_stream

        context = current_stream.get()
        initial = FirstExplanationSubmissionResponse(
            session=to_session_response(repository, session), grading=to_grading_response(grading)
        )
        context.registry.update_result(
            context.run_id, initial.model_dump(mode="json", by_alias=True)
        )
        await task
        database_session.expire_all()
        database_session.refresh(session)
        database_session.refresh(grading)
    return FirstExplanationSubmissionResponse(
        session=to_session_response(repository, session), grading=to_grading_response(grading)
    )


@router.get("/{session_id}/grading", response_model=FirstExplanationGradingResponse | None)
def get_grading(
    session_id: int, database_session: DatabaseSession, current_user: CurrentUser
):
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    record = _record_for(database_session, session.id)
    return None if record is None else to_grading_response(record)


@router.post(
    "/{session_id}/grading/retry",
    response_model=FirstExplanationGradingResponse,
    status_code=202,
)
async def retry_grading(
    session_id: int,
    request: Request,
    database_session: DatabaseSession,
    current_user: CurrentUser,
):
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    record = _record_for(database_session, session.id)
    if record is None:
        raise HTTPException(status_code=404, detail="首次评分记录不存在")
    if record.status not in {"FAILED"}:
        raise HTTPException(status_code=409, detail="当前评分状态不能重试")
    begin_ai_run(database_session, session, request)
    record.status = "PENDING"
    record.error_message = None
    database_session.commit()
    task = _schedule_grading_retry(
        request=request,
        session_id=session.id,
        attempt_id=record.attempt_id,
        grading_id=record.id,
        run_id=request.state.ai_run_id,
    )
    if getattr(request.state, "stream_managed", False):
        await task
        database_session.expire_all()
        database_session.refresh(record)
    return to_grading_response(record)


@router.post("/{session_id}/grading/acknowledge", response_model=FirstExplanationGradingResponse)
def acknowledge_grading(
    session_id: int, database_session: DatabaseSession, current_user: CurrentUser
):
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    record = _record_for(database_session, session.id)
    if record is None:
        raise HTTPException(status_code=404, detail="首次评分记录不存在")
    if record.status not in {"SUCCEEDED", "FAILED"}:
        raise HTTPException(status_code=409, detail="评分尚未完成")
    record.acknowledged_at = record.acknowledged_at or datetime.now(UTC)
    database_session.commit()
    database_session.refresh(record)
    return to_grading_response(record)
