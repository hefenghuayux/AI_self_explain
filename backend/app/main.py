import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response
from sqlalchemy.orm import sessionmaker

from app.api.audit import router as audit_router
from app.api.health import router as health_router
from app.api.questions import router as questions_router
from app.api.sessions import router as sessions_router
from app.core.config import Settings
from app.core.database import create_database_engine, prepare_runtime_directories
from app.core.logging import configure_logging, new_request_id, request_id_context
from app.services.realtime_asr import configure_dashscope

configure_logging()
logger = logging.getLogger(__name__)


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        prepare_runtime_directories(settings)
        configure_logging(settings.log_dir, settings.log_max_size_mib, settings.log_backup_count)
        configure_dashscope(settings)
        database_engine = create_database_engine(settings)
        application.state.database_engine = database_engine
        application.state.database_session_factory = sessionmaker(bind=database_engine)
        logger.info("应用启动完成", extra={"operation": "application_startup"})
        try:
            yield
        finally:
            database_engine.dispose()
            logger.info("应用已停止", extra={"operation": "application_shutdown"})

    application = FastAPI(title="AI 自讲 Demo API", version="0.1.0", lifespan=lifespan)
    application.state.settings = settings
    application.include_router(health_router, prefix="/api")
    application.include_router(questions_router, prefix="/api")
    application.include_router(sessions_router, prefix="/api")
    application.include_router(audit_router, prefix="/api")

    @application.middleware("http")
    async def request_context_middleware(request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        token = request_id_context.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_context.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response

    return application


app = create_app(Settings())
