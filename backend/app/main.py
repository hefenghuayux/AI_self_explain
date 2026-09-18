import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import sessionmaker

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.questions import router as questions_router
from app.api.session_events import router as session_events_router
from app.api.sessions import router as sessions_router
from app.core.config import Settings
from app.core.database import create_database_engine, prepare_runtime_directories
from app.core.logging import (
    bind_trace_context,
    configure_logging,
    new_correlation_id,
    reset_trace_context,
)
from app.services.context_compaction import CompactionError
from app.services.context_runtime import ContextMiddleware, ContextRuntime
from app.services.realtime_asr import configure_dashscope

SESSION_PATH_PATTERN = re.compile(r"^/api/sessions/(?P<session_id>\d+)(?:/|$)")
configure_logging()
logger = logging.getLogger(__name__)


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        prepare_runtime_directories(settings)
        configure_logging(settings.log_dir, settings.log_max_size_mib, settings.log_backup_count)
        configure_dashscope(settings)
        database_engine = create_database_engine(settings)
        ai_http_client = httpx.Client(timeout=settings.ai_request_timeout_seconds)
        application.state.database_engine = database_engine
        application.state.database_session_factory = sessionmaker(bind=database_engine)
        application.state.ai_http_client = ai_http_client
        application.state.context_runtime = ContextRuntime(
            settings, ai_http_client, application.state.database_session_factory
        )
        logger.info(
            "应用启动完成",
            extra={"eventName": "application.started", "operation": "application_startup"},
        )
        try:
            yield
        finally:
            ai_http_client.close()
            database_engine.dispose()
            logger.info(
                "应用已停止",
                extra={"eventName": "application.stopped", "operation": "application_shutdown"},
            )

    application = FastAPI(title="AI 自讲 Demo API", version="0.1.0", lifespan=lifespan)
    application.state.settings = settings
    application.add_middleware(ContextMiddleware)

    @application.exception_handler(CompactionError)
    async def compaction_error_handler(request: Request, error: CompactionError):
        return JSONResponse(
            status_code=503, content={"detail": {"code": error.code, "message": str(error)}}
        )
    application.include_router(health_router, prefix="/api")
    application.include_router(auth_router, prefix="/api")
    application.include_router(questions_router, prefix="/api")
    application.include_router(sessions_router, prefix="/api")
    application.include_router(session_events_router, prefix="/api")

    @application.middleware("http")
    async def request_context_middleware(request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or new_correlation_id()
        trace_id = request.headers.get("X-Trace-ID") or request_id
        session_match = SESSION_PATH_PATTERN.match(request.url.path)
        session_id = int(session_match.group("session_id")) if session_match else None
        tokens = bind_trace_context(
            request_id=request_id,
            trace_id=trace_id,
            span_id=new_correlation_id(),
            session_id=session_id,
        )
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "请求处理失败",
                extra={"eventName": "request.failed", "operation": "http_request"},
            )
            raise
        finally:
            if "response" in locals():
                elapsed_ms = round((time.perf_counter() - started_at) * 1000)
                response.headers["X-Request-ID"] = request_id
                response.headers["X-Trace-ID"] = trace_id
                logger.info(
                    "请求处理完成",
                    extra={
                        "eventName": "request.completed",
                        "operation": "http_request",
                        "method": request.method,
                        "path": request.url.path,
                        "durationMs": elapsed_ms,
                        "statusCode": response.status_code,
                    },
                )
            reset_trace_context(tokens)
        return response

    return application


app = create_app(Settings())
