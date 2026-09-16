import argparse
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from sqlalchemy import Engine, MetaData, create_engine, func, select

from app.core.config import Settings
from app.core.database import create_database_engine

TABLE_ORDER = (
    "users",
    "auth_sessions",
    "questions",
    "sessions",
    "audio_files",
    "explanation_attempts",
    "external_call_records",
    "ai_evaluations",
    "support_events",
    "student_submissions",
    "state_transition_events",
    "session_events",
)
TARGET_TABLE_NAMES = {"questions": "self_explain_questions"}


@dataclass(frozen=True)
class LegacyMigrationResult:
    migrated_counts: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def migrate_legacy_sqlite(source_engine: Engine, target_engine: Engine) -> LegacyMigrationResult:
    source_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)
    target_metadata = MetaData()
    target_metadata.reflect(bind=target_engine)

    source_tables = [name for name in TABLE_ORDER if name in source_metadata.tables]
    with source_engine.connect() as source_connection:
        source_rows = {
            name: list(source_connection.execute(select(source_metadata.tables[name])).mappings())
            for name in source_tables
        }

    migrated_counts: dict[str, int] = {}
    with target_engine.begin() as target_connection:
        _ensure_target_is_empty(target_connection, target_metadata, source_tables)
        for source_table_name in source_tables:
            target_table_name = TARGET_TABLE_NAMES.get(source_table_name, source_table_name)
            target_table = target_metadata.tables[target_table_name]
            rows = [
                _target_values(source_table_name, source_row, target_table)
                for source_row in source_rows[source_table_name]
            ]
            if rows:
                target_connection.execute(target_table.insert(), rows)
            migrated_counts[target_table_name] = len(rows)
    return LegacyMigrationResult(migrated_counts=migrated_counts)


def _ensure_target_is_empty(
    target_connection: object,
    target_metadata: MetaData,
    source_table_names: list[str],
) -> None:
    for source_table_name in source_table_names:
        target_table_name = TARGET_TABLE_NAMES.get(source_table_name, source_table_name)
        target_table = target_metadata.tables[target_table_name]
        count = target_connection.scalar(select(func.count()).select_from(target_table))
        if count:
            raise ValueError(f"目标表必须为空：{target_table_name}")


def _target_values(
    source_table_name: str,
    source_row: Mapping[str, object],
    target_table: object,
) -> dict[str, object]:
    target_columns = {column.name for column in target_table.columns}
    values = {name: value for name, value in source_row.items() if name in target_columns}
    if source_table_name == "questions":
        values.update(
            {
                "tiku_question_id": None,
                "grade_period": None,
                "subject": None,
                "q_type": None,
                "difficulty_level": None,
                "review": None,
                "topics": None,
                "method": None,
            }
        )
    if source_table_name == "ai_evaluations":
        values["evaluation_mode"] = "FULL_RUBRIC"
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="迁移旧 SQLite AI 自讲历史数据")
    parser.add_argument(
        "--source-database-url", required=True, help="旧 SQLite 数据库 SQLAlchemy URL"
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    settings = Settings()
    source_engine = create_engine(arguments.source_database_url)
    target_engine = create_database_engine(settings)
    try:
        result = migrate_legacy_sqlite(source_engine, target_engine)
        print(json.dumps(result.as_dict(), ensure_ascii=False))
    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == "__main__":
    main()
