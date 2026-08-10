from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.core.config import Settings
from app.core.database import (
    check_database_connection,
    create_database_engine,
    prepare_runtime_directories,
)


def test_sqlite_database_connects(settings: Settings) -> None:
    prepare_runtime_directories(settings)
    engine: Engine = create_database_engine(settings)
    try:
        check_database_connection(engine)
    finally:
        engine.dispose()


def test_runtime_sqlite_connection_enforces_foreign_keys(settings: Settings) -> None:
    engine = create_database_engine(settings)
    try:
        with engine.begin() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            connection.execute(text("CREATE TABLE parents (id INTEGER PRIMARY KEY)"))
            connection.execute(
                text(
                    "CREATE TABLE children ("
                    "id INTEGER PRIMARY KEY, "
                    "parent_id INTEGER NOT NULL REFERENCES parents(id)"
                    ")"
                )
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO children (id, parent_id) VALUES (1, 999)"))
    finally:
        engine.dispose()


def test_alembic_rejects_existing_foreign_key_violations(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_engine = create_engine(settings.database_url)
    try:
        with setup_engine.begin() as connection:
            connection.execute(text("CREATE TABLE parents (id INTEGER PRIMARY KEY)"))
            connection.execute(
                text(
                    "CREATE TABLE children ("
                    "id INTEGER PRIMARY KEY, "
                    "parent_id INTEGER NOT NULL REFERENCES parents(id)"
                    ")"
                )
            )
            connection.execute(text("INSERT INTO children (id, parent_id) VALUES (1, 999)"))
    finally:
        setup_engine.dispose()

    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    alembic_config = Config(str(Path(__file__).parents[2] / "alembic.ini"))

    with pytest.raises(RuntimeError, match="数据库存在外键违规，停止迁移"):
        command.upgrade(alembic_config, "head")
