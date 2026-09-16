import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text

from app.core.config import Settings


def create_database_engine(settings: Settings) -> Engine:
    if _is_sqlite_database_url(settings.database_url):
        engine = create_engine(
            settings.database_url,
            connect_args={"timeout": settings.database_busy_timeout_seconds},
        )
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
        return engine

    engine = create_engine(settings.database_url)
    return engine


def prepare_runtime_directories(settings: Settings) -> None:
    settings.audio_storage_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    database_path = _sqlite_database_path(settings.database_url)
    if database_path is not None:
        database_path.parent.mkdir(parents=True, exist_ok=True)


def check_database_connection(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def _enable_sqlite_foreign_keys(
    dbapi_connection: sqlite3.Connection,
    _connection_record: Any,
) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
    finally:
        cursor.close()


def _sqlite_database_path(database_url: str) -> Path | None:
    if not _is_sqlite_database_url(database_url):
        return None

    path_text = database_url.split("///", maxsplit=1)[1]
    if path_text == ":memory:":
        return None
    return Path(path_text)


def _is_sqlite_database_url(database_url: str) -> bool:
    return database_url.startswith(("sqlite:///", "sqlite+pysqlite:///"))
