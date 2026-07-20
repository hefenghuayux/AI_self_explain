from pathlib import Path

from sqlalchemy import Engine, create_engine, text

from app.core.config import Settings


def create_database_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        connect_args={"timeout": settings.database_busy_timeout_seconds},
    )


def prepare_runtime_directories(settings: Settings) -> None:
    settings.audio_storage_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    database_path = _sqlite_database_path(settings.database_url)
    if database_path is not None:
        database_path.parent.mkdir(parents=True, exist_ok=True)


def check_database_connection(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def _sqlite_database_path(database_url: str) -> Path | None:
    path_text = database_url.split("///", maxsplit=1)[1]
    if path_text == ":memory:":
        return None
    return Path(path_text)
