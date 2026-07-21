import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app.api.health import router as health_router
from app.api.questions import router as questions_router
from app.api.sessions import router as sessions_router
from app.core.config import Settings
from app.core.database import create_database_engine, prepare_runtime_directories
from app.core.logging import configure_logging
from app.services.realtime_asr import configure_dashscope

configure_logging()
logger = logging.getLogger(__name__)


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        prepare_runtime_directories(settings)
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
    return application


app = create_app(Settings())
