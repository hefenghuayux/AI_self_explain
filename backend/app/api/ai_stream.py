"""Run student operations independently of their authenticated SSE subscriptions."""

import asyncio
import inspect
import json
import logging
from types import SimpleNamespace
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import inspect as inspect_database
from sqlalchemy import select

from app.api import first_explanation_grading, sessions
from app.core.auth import CurrentUser, DatabaseSession
from app.models.ai_run import AIRun
from app.models.session import Session
from app.models.user import User
from app.repositories.sessions import SessionRepository
from app.schemas.session import (
    AppealInput,
    DoubtRequestInput,
    GuidedAnswersInput,
    HelpRequestInput,
    MasteryCheckAnswersInput,
    SolutionUnderstandingInput,
    TextAttemptInput,
)
from app.schemas.session_step import StepAttemptInput
from app.services.ai_evaluation import AIServiceUnavailableError
from app.services.ai_run import AIRunCancelled, begin_run, bind_run, cancel_run, finish_run
from app.services.ai_stream import StreamContext, current_stream, terminal_snapshot
from app.services.context_compaction import CompactionError
from app.services.context_runtime import RequestContext, current_context
from app.services.independent_doubt import IndependentDoubtInput, accept_doubt, answer_doubt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["ai-stream"])


def _failure_flow_stage(run_snapshot: dict[str, object]) -> str:
    flow_stage = run_snapshot.get("flowStage")
    return (
        flow_stage
        if isinstance(flow_stage, str) and flow_stage != "AI_EVALUATING"
        else "CAPTURING_INPUT"
    )


class AIRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID = Field(alias="runId")
    operation: Literal[
        "text-attempts",
        "step-attempts",
        "graded-step-attempts",
        "request-support",
        "ask-doubt",
        "independent-doubt",
        "guided-answers",
        "appeal",
        "full-solution-understanding",
        "mastery-check-answers",
        "grading/retry",
    ]
    input: dict[str, object] = Field(default_factory=dict)


OPERATIONS = {
    "text-attempts": (sessions.submit_text_attempt, TextAttemptInput, "attempt_input"),
    "step-attempts": (sessions.submit_step_attempt, StepAttemptInput, "attempt_input"),
    "graded-step-attempts": (
        first_explanation_grading.submit_graded_step_attempt,
        StepAttemptInput,
        "attempt_input",
    ),
    "request-support": (sessions.request_support, HelpRequestInput, "action_input"),
    "ask-doubt": (sessions.ask_doubt, DoubtRequestInput, "action_input"),
    "guided-answers": (sessions.submit_guided_answers, GuidedAnswersInput, "action_input"),
    "appeal": (sessions.appeal, AppealInput, "appeal_input"),
    "full-solution-understanding": (
        sessions.respond_to_first_solution,
        SolutionUnderstandingInput,
        "understanding_input",
    ),
    "mastery-check-answers": (
        sessions.submit_mastery_check_answers,
        MasteryCheckAnswersInput,
        "answers_input",
    ),
    "grading/retry": (first_explanation_grading.retry_grading, None, None),
}


def _call_operation(
    app,
    user_id: int,
    session_id: int,
    run_id: str,
    operation: str,
    payload,
    headers: dict[str, str],
):
    endpoint, _, input_name = OPERATIONS[operation]
    with app.state.database_session_factory() as db:
        bind_run(db, session_id, run_id, app.state.context_runtime)
        user = db.get(User, user_id)
        request = SimpleNamespace(
            app=app,
            headers=headers,
            state=SimpleNamespace(ai_run_id=run_id, stream_managed=True),
        )
        arguments = {
            "session_id": session_id,
            "database_session": db,
            "current_user": user,
        }
        if "request" in inspect.signature(endpoint).parameters:
            arguments["request"] = request
        if input_name is not None:
            arguments[input_name] = payload
        result = endpoint(**arguments)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        return result.model_dump(mode="json", by_alias=True)


def _stream_error(error: Exception) -> dict[str, object]:
    if isinstance(error, HTTPException):
        detail = error.detail
        if isinstance(detail, dict):
            return {
                "code": detail.get("code", "AI_OPERATION_FAILED"),
                "message": detail.get("message", str(detail)),
                "status": error.status_code,
            }
        return {"code": "AI_OPERATION_FAILED", "message": str(detail), "status": error.status_code}
    if isinstance(error, AIServiceUnavailableError):
        return {"code": "AI_SERVICE_UNAVAILABLE", "message": str(error), "status": 503}
    if isinstance(error, CompactionError):
        code = "AI_SERVICE_UNAVAILABLE" if error.is_service_failure else error.code
        return {"code": code, "message": str(error), "status": 503}
    return {"code": "AI_OPERATION_FAILED", "message": "AI 生成失败，请稍后重试。", "status": 500}


async def _execute(
    app,
    user_id: int,
    session_id: int,
    run_id: str,
    operation: str,
    payload,
    headers: dict[str, str],
) -> None:
    runtime = app.state.context_runtime
    registry = app.state.ai_stream_registry
    # Use the same session lock as ordinary requests and history compaction.
    lock = runtime.locks.setdefault(session_id, asyncio.Lock())
    runtime.users[session_id] = runtime.users.get(session_id, 0) + 1
    stream_token = current_stream.set(StreamContext(registry, run_id, session_id))
    context = RequestContext(runtime, session_id)
    context_token = current_context.set(context)
    try:
        async with lock:
            result = None
            error_detail = None
            cancelled = False
            try:
                result = await asyncio.to_thread(
                    _call_operation,
                    app,
                    user_id,
                    session_id,
                    run_id,
                    operation,
                    payload,
                    headers,
                )
            except AIRunCancelled:
                cancelled = True
            except Exception as error:
                logger.exception("流式 AI 运行失败 session=%s run=%s", session_id, run_id)
                error_detail = _stream_error(error)
            else:
                if "activeRunId" in result:
                    result["activeRunId"] = None
                elif "session" in result:
                    result["session"]["activeRunId"] = None
            # Never publish completion while cancellation can still roll back the result.
            snapshot = registry.snapshot(run_id)
            with runtime.database_session_factory() as db:
                session = db.scalar(
                    select(Session).where(Session.id == session_id).with_for_update()
                )
                record = db.scalar(select(AIRun).where(AIRun.id == run_id).with_for_update())
                handle = runtime.run_handles.get(run_id)
                cancelled = cancelled or record.status == "CANCELLED" or (
                    handle is not None and handle.cancelled.is_set()
                )
                if cancelled:
                    if session.active_run_id == run_id:
                        cancel_run(db, session, run_id, runtime)
                else:
                    if error_detail and session.flow_stage == "AI_EVALUATING":
                        SessionRepository(db).record_ai_service_failure(
                            session=session,
                            flow_stage=_failure_flow_stage(record.snapshot),
                            trigger_type="AI_STREAM_FAILED",
                        )
                        # The existing failure recorder commits; reacquire the cancellation guard.
                        session = db.scalar(
                            select(Session).where(Session.id == session_id).with_for_update()
                            .execution_options(populate_existing=True)
                        )
                        record = db.scalar(
                            select(AIRun).where(AIRun.id == run_id).with_for_update()
                            .execution_options(populate_existing=True)
                        )
                        cancelled = record.status == "CANCELLED"
                    if not cancelled:
                        record.checkpoints = {
                            **record.checkpoints,
                            "stream": terminal_snapshot(
                                snapshot, result=result, error=error_detail
                            ),
                        }
                        finish_run(db, session_id, run_id, runtime)
            registry.finish(run_id, result=result, error=error_detail, cancelled=cancelled)
            if not cancelled and context.needs_compaction and context.prefix:
                await asyncio.to_thread(runtime.compact_after_response, context)
    finally:
        current_stream.reset(stream_token)
        current_context.reset(context_token)
        runtime.users[session_id] -= 1
        if runtime.users[session_id] == 0:
            del runtime.users[session_id]
            del runtime.locks[session_id]


async def _execute_doubt(app, session_id: int, run_id: str) -> None:
    registry = app.state.ai_stream_registry
    stream_token = current_stream.set(StreamContext(registry, run_id, session_id))
    try:
        try:
            result = await asyncio.to_thread(answer_doubt, app, session_id, run_id)
        except Exception as error:
            logger.exception("独立答疑失败 session=%s run=%s", session_id, run_id)
            detail = _stream_error(error)
            snapshot = registry.snapshot(run_id)
            with app.state.database_session_factory() as db:
                record = db.scalar(select(AIRun).where(AIRun.id == run_id).with_for_update())
                record.status = "FAILED"
                record.checkpoints = {
                    **record.checkpoints,
                    "stream": terminal_snapshot(snapshot, error=detail),
                }
                db.commit()
            registry.finish(run_id, error=detail)
        else:
            registry.finish(run_id, result=result)
    finally:
        current_stream.reset(stream_token)


@router.post("/{session_id}/ai-runs", status_code=202)
async def submit_ai_run(
    session_id: int,
    run_input: AIRunInput,
    request: Request,
    database_session: DatabaseSession,
    current_user: CurrentUser,
):
    repository = SessionRepository(database_session)
    session = sessions.get_session_or_404(repository, session_id, current_user)
    run_id = str(run_input.run_id)
    existing = database_session.get(AIRun, run_id)
    if existing is not None:
        if existing.session_id != session_id:
            raise HTTPException(status_code=404, detail="AI 运行不存在")
        snapshot = request.app.state.ai_stream_registry.snapshot(run_id)
        if snapshot is None:
            raise HTTPException(status_code=409, detail="AI 运行标识已使用")
        return {"runId": run_id}
    if run_input.operation == "independent-doubt":
        try:
            payload = IndependentDoubtInput.model_validate(run_input.input)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        accept_doubt(database_session, session, run_id, payload, request.app.state.settings)
        request.app.state.ai_stream_registry.create(run_id, session_id)
        task = asyncio.create_task(_execute_doubt(request.app, session_id, run_id))
        request.app.state.ai_stream_tasks.add(task)
        task.add_done_callback(request.app.state.ai_stream_tasks.discard)
        return {"runId": run_id}
    _, schema, _ = OPERATIONS[run_input.operation]
    try:
        payload = schema.model_validate(run_input.input) if schema else None
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if schema is None and run_input.input:
        raise HTTPException(status_code=422, detail="评分重试不接受额外输入")
    # Recheck against the locked row, rather than the earlier ownership-read snapshot.
    session = database_session.scalar(
        select(Session).where(Session.id == session_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if session.active_run_id:
        raise HTTPException(status_code=409, detail="当前 AI 仍在生成，请等待或中断")
    if payload is not None:
        sessions.validate_version(session, payload.version)
    try:
        begin_run(database_session, session, run_id, request.app.state.context_runtime)
    except (ValueError, AIRunCancelled) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    request.app.state.ai_stream_registry.create(run_id, session_id)
    request.state.ai_run_id = run_id
    request.state.stream_background = True
    headers = {
        "X-AI-Run-ID": run_id,
        "X-Teacher-Speech-Prewarm": request.headers.get("X-Teacher-Speech-Prewarm", "false"),
    }
    task = asyncio.create_task(
        _execute(
            request.app,
            current_user.id,
            session_id,
            run_id,
            run_input.operation,
            payload,
            headers,
        )
    )
    request.app.state.ai_stream_tasks.add(task)
    task.add_done_callback(request.app.state.ai_stream_tasks.discard)
    return {"runId": run_id}


@router.get("/{session_id}/independent-doubts")
def list_independent_doubts(
    session_id: int,
    request: Request,
    database_session: DatabaseSession,
    current_user: CurrentUser,
):
    sessions.get_session_or_404(SessionRepository(database_session), session_id, current_user)
    records = database_session.scalars(
        select(AIRun).where(AIRun.session_id == session_id)
        .order_by(AIRun.created_at, AIRun.id)
    )
    result = []
    for record in records:
        if record.snapshot.get("operation") != "independent-doubt":
            continue
        snapshot = request.app.state.ai_stream_registry.snapshot(record.id)
        result.append({
            "runId": record.id,
            "status": snapshot["status"] if snapshot else "FAILED",
            "question": record.snapshot["input"]["doubtText"],
            "result": snapshot.get("result") if snapshot else None,
            "error": snapshot.get("error") if snapshot else {
                "code": "AI_RUN_INTERRUPTED", "status": 503,
                "message": "服务重启，本次生成已中断，请重新提交。",
            },
        })
    return result


@router.get("/{session_id}/ai-runs/{run_id}/stream")
async def subscribe_ai_run(
    session_id: int,
    run_id: UUID,
    request: Request,
    database_session: DatabaseSession,
    current_user: CurrentUser,
):
    sessions.get_session_or_404(SessionRepository(database_session), session_id, current_user)
    record = database_session.get(AIRun, str(run_id))
    if record is None or record.session_id != session_id:
        raise HTTPException(status_code=404, detail="AI 运行不存在")
    registry = request.app.state.ai_stream_registry
    if registry.snapshot(str(run_id)) is None:
        raise HTTPException(status_code=404, detail="AI 流记录不存在")

    async def events():
        revision = -1
        heartbeat = asyncio.get_running_loop().time()
        while not await request.is_disconnected():
            snapshot = registry.snapshot(str(run_id))
            if snapshot is None:
                return
            if snapshot["revision"] != revision:
                revision = snapshot["revision"]
                data = json.dumps(snapshot, ensure_ascii=True)
                yield f"id: {revision}\nevent: snapshot\ndata: {data}\n\n"
            if snapshot["status"] != "RUNNING":
                return
            now = asyncio.get_running_loop().time()
            if now - heartbeat >= 15:
                heartbeat = now
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def recover_interrupted_streams(app) -> None:
    """Single-worker startup: mark persisted unfinished streams, never replay model calls."""
    runtime = app.state.context_runtime
    if not inspect_database(app.state.database_engine).has_table("ai_runs"):
        return
    with runtime.database_session_factory() as db:
        records = list(db.scalars(
            select(AIRun).where(AIRun.status.in_(["ACTIVE", "COMPLETED", "CANCELLED", "FAILED"]))
        ))
        pending = [
            (record.id, record.session_id, record.status, record.checkpoints.get("stream"))
            for record in records
            if record.status == "ACTIVE"
            or record.checkpoints.get("stream", {}).get("status") == "RUNNING"
        ]
    for run_id, session_id, status, snapshot in pending:
        if status == "CANCELLED":
            app.state.ai_stream_registry.finish(run_id, cancelled=True)
            continue
        with runtime.database_session_factory() as db:
            record = db.get(AIRun, run_id)
            if record.snapshot.get("operation") == "independent-doubt":
                if snapshot and snapshot["status"] != "RUNNING":
                    record.status = "COMPLETED" if snapshot["status"] == "SUCCEEDED" else "FAILED"
                else:
                    record.status = "FAILED"
                    if snapshot is None:
                        # A crash may occur after acceptance and before stream registration.
                        snapshot = {
                            "runId": run_id, "status": "RUNNING", "revision": 0,
                            "channels": {}, "error": None, "result": None,
                        }
                    record.checkpoints = {
                        **record.checkpoints,
                        "stream": terminal_snapshot(snapshot, error={
                            "code": "AI_RUN_INTERRUPTED", "status": 503,
                            "message": "服务重启，本次生成已中断，请重新提交。",
                        }),
                    }
                db.commit()
                continue
            session = db.get(Session, session_id)
            if snapshot and snapshot["status"] != "RUNNING":
                # Result persistence won the crash race: preserve it and release the session.
                finish_run(db, session_id, run_id, runtime)
                record = db.get(AIRun, run_id)
                if record is not None and snapshot["status"] == "FAILED":
                    record.status = "FAILED"
                    db.commit()
                continue
            if session is not None and session.active_run_id == run_id:
                cancel_run(db, session, run_id, runtime)
            record = db.get(AIRun, run_id)
            if record is not None:
                record.status = "FAILED"
                db.commit()
        if snapshot is None:
            app.state.ai_stream_registry.create(run_id, session_id)
        app.state.ai_stream_registry.finish(
            run_id,
            error={
                "code": "AI_RUN_INTERRUPTED",
                "status": 503,
                "message": "服务重启，本次生成已中断，请重新提交。",
            },
        )
