from sqlalchemy import Engine

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
