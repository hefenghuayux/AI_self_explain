"""Request-scoped history projection and single-process session serialization."""

import asyncio
import json
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass, field

from fastapi import HTTPException
from starlette.responses import JSONResponse

from app.models.session import Session
from app.services.context_compaction import CompactionError, ContextCompactor
from app.services.context_history import build_shared_history, load_history
from app.services.context_tokens import ContextTokenizer

logger = logging.getLogger(__name__)


@dataclass
class RequestContext:
    runtime: "ContextRuntime"
    session_id: int
    needs_compaction: bool = False
    prefix: list | None = None
    recovered: set[str] = field(default_factory=set)


current_context: ContextVar[RequestContext | None] = ContextVar("context_request", default=None)


def note_success(total_tokens: object) -> None:
    context = current_context.get()
    if context is not None and type(total_tokens) is int:
        settings = context.runtime.settings
        if total_tokens >= (
            settings.ai_context_window_tokens * settings.context_compaction_after_response_ratio
        ):
            context.needs_compaction = True


def prepare_request(request, database_session, session, *, exclude_attempt_id=None):
    """Update only the shared-history layer and matching audit fields."""
    history = build_shared_history(database_session, session, exclude_attempt_id=exclude_attempt_id)
    request.transport.messages[2].content = json.dumps(history, ensure_ascii=False)
    request.blocks.memory_context = history
    request.blocks.session_context.pop("teachingHistory", None)
    request.blocks.session_context["progressContext"] = history
    request.privacy.contains_memory = bool(history.get("summary"))
    context = current_context.get()
    if context is not None:
        request.transport.extra_body["max_tokens"] = context.runtime.settings.ai_max_output_tokens
        context.prefix = request.transport.messages[:2]
    return request


def preflight(request, database_session, session) -> None:
    context = current_context.get()
    if context is None:
        return
    prepare_request(request, database_session, session)
    settings = context.runtime.settings
    estimated = context.runtime.tokenizer.count_messages(request.transport.messages)
    if estimated + settings.ai_max_output_tokens >= (
        settings.ai_context_window_tokens * settings.context_compaction_before_request_ratio
    ):
        before = (session.version, session.status, session.flow_stage, session.round)
        context.runtime.compactor.compact(database_session, session, request.transport.messages[:2])
        database_session.refresh(session)
        if (session.version, session.status, session.flow_stage, session.round) != before:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "SESSION_VERSION_CONFLICT",
                    "message": "会话在压缩期间已变化，请刷新后重试",
                    "sessionId": session.id,
                },
            )


def preflight_submission(
    database_session,
    session,
    settings,
    *,
    text=None,
    main_draft="",
    doubt_text=None,
    support_event=None,
    answers=None,
):
    from app.models.explanation_attempt import ExplanationAttempt
    from app.models.question import Question
    from app.services.ai_evaluation import _render_prompt
    from app.services.ai_support import (
        _render_answer_assessment_prompt,
        _render_support_prompt,
    )

    question = database_session.get(Question, session.question_id)
    options = dict(
        question=question,
        session=session,
        validation_errors=[],
        model=settings.ai_model,
        prompt_version=settings.prompt_version,
        reasoning_effort=settings.ai_reasoning_effort,
    )
    if text is not None:
        request = _render_prompt(
            **options,
            attempt=ExplanationAttempt(confirmed_text=text),
        )
    elif support_event is not None:
        request = _render_answer_assessment_prompt(
            **options,
            support_event=support_event,
            answers=answers,
        )
    else:
        request = _render_support_prompt(**options, main_draft=main_draft, doubt_text=doubt_text)
    preflight(request, database_session, session)


def recover_overflow(error, request, database_session, session, *, exclude_attempt_id=None):
    """Called once per business call, outside normal transport retries."""
    context = current_context.get()
    if context is None:
        raise CompactionError("CONTEXT_COMPACTION_UNAVAILABLE", str(error)) from error
    context.runtime.compactor.compact(
        database_session,
        session,
        request.transport.messages[:2],
        exclude_attempt_id=exclude_attempt_id,
    )
    prepare_request(request, database_session, session, exclude_attempt_id=exclude_attempt_id)


def evaluate_request(
    client,
    request,
    database_session,
    session,
    requested_event_id,
    run_id,
    *,
    exclude_attempt_id=None,
):
    from app.services.ai_evaluation import AITransportError
    from app.services.session_event_log import SessionEventLog

    try:
        return client.evaluate(request), requested_event_id
    except AITransportError as error:
        if error.error_type != "CONTEXT_WINDOW_EXCEEDED":
            raise
        context = current_context.get()
        if context is not None:
            if request.purpose in context.recovered:
                raise CompactionError("CONTEXT_WINDOW_EXCEEDED_AFTER_COMPACTION") from error
            context.recovered.add(request.purpose)
        log = SessionEventLog(database_session)
        log.append_model_failed(
            session_id=session.id,
            run_id=run_id,
            error_type=error.error_type,
            message=str(error),
            duration_ms=error.duration_ms,
            parent_event_id=requested_event_id,
        )
        recover_overflow(
            error, request, database_session, session, exclude_attempt_id=exclude_attempt_id
        )
        retried = log.append_model_requested(
            session_id=session.id,
            run_id=run_id,
            request=request,
            provider=client.settings.ai_provider,
            parent_event_id=requested_event_id,
        )
        try:
            return client.evaluate(request), retried.event_id
        except AITransportError as retry_error:
            log.append_model_failed(
                session_id=session.id,
                run_id=run_id,
                error_type=retry_error.error_type,
                message=str(retry_error),
                duration_ms=retry_error.duration_ms,
                parent_event_id=retried.event_id,
            )
            code = (
                "CONTEXT_WINDOW_EXCEEDED_AFTER_COMPACTION"
                if retry_error.error_type == "CONTEXT_WINDOW_EXCEEDED"
                else "CONTEXT_COMPACTION_RETRY_FAILED"
            )
            raise CompactionError(code, str(retry_error)) from retry_error


class ContextRuntime:
    def __init__(self, settings, http_client, database_session_factory):
        self.settings = settings
        self.tokenizer = ContextTokenizer()
        self.compactor = ContextCompactor(settings, http_client, self.tokenizer)
        self.database_session_factory = database_session_factory
        self.locks: dict[int, asyncio.Lock] = {}
        self.users: dict[int, int] = {}
        self.failed_history: dict[int, str] = {}

    def compact_after_response(self, context: RequestContext):
        fingerprint = None
        try:
            with self.database_session_factory() as db:
                session = db.get(Session, context.session_id)
                if session is None:
                    return
                fingerprint = load_history(db, session).fingerprint
                if self.failed_history.get(session.id) == fingerprint:
                    return
                changed = self.compactor.compact(db, session, context.prefix)
                if changed:
                    self.failed_history.pop(session.id, None)
                else:
                    self.failed_history[session.id] = fingerprint
        except Exception:
            if fingerprint is not None:
                self.failed_history[context.session_id] = fingerprint
            logger.exception("后台历史压缩失败 session=%s", context.session_id)


class ContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        match = re.fullmatch(r"/api/sessions/(\d+)(?:/.*)?", scope.get("path", ""))
        if scope["type"] != "http" or scope.get("method") != "POST" or not match:
            await self.app(scope, receive, send)
            return
        runtime = scope["app"].state.context_runtime
        session_id = int(match.group(1))
        lock = runtime.locks.setdefault(session_id, asyncio.Lock())
        runtime.users[session_id] = runtime.users.get(session_id, 0) + 1
        acquired = False
        token = None
        try:
            try:
                await asyncio.wait_for(
                    lock.acquire(), runtime.settings.context_compaction_wait_timeout_seconds
                )
                acquired = True
            except TimeoutError:
                response = JSONResponse(
                    {
                        "detail": {
                            "code": "CONTEXT_COMPACTION_TIMEOUT",
                            "message": "等待会话历史压缩超时，请重试",
                        }
                    },
                    status_code=503,
                )
                await response(scope, receive, send)
                return
            context = RequestContext(runtime, session_id)
            token = current_context.set(context)
            await self.app(scope, receive, send)
            # ASGI has sent the complete response and closed the request DB session.
            if context.needs_compaction and context.prefix:
                task = asyncio.create_task(
                    asyncio.to_thread(runtime.compact_after_response, context)
                )
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise
        finally:
            if token is not None:
                current_context.reset(token)
            if acquired:
                lock.release()
            runtime.users[session_id] -= 1
            if runtime.users[session_id] == 0:
                del runtime.users[session_id]
                del runtime.locks[session_id]
