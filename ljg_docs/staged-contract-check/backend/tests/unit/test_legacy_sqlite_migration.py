from sqlalchemy import (
    JSON,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
)

import app.models  # noqa: F401
from app.models.base import Base
from app.scripts.migrate_legacy_sqlite import migrate_legacy_sqlite


def test_migrate_legacy_sqlite_preserves_ids_relationships_and_rubric_mode() -> None:
    source_engine = create_engine("sqlite:///:memory:")
    target_engine = create_engine("sqlite:///:memory:")
    source_metadata = MetaData()
    users = Table(
        "users",
        source_metadata,
        Column("id", Integer, primary_key=True),
        Column("username", String),
        Column("password_hash", String),
        Column("full_name", String),
        Column("role", String),
    )
    questions = Table(
        "questions",
        source_metadata,
        Column("id", Integer, primary_key=True),
        Column("question_content", Text),
        Column("standard_answer", Text),
        Column("rubric_points", JSON),
        Column("common_errors", JSON),
        Column("alternative_solutions", JSON),
        Column("layered_hints", JSON),
        Column("guided_questions", JSON),
        Column("full_solution", Text),
    )
    sessions = Table(
        "sessions",
        source_metadata,
        Column("id", Integer, primary_key=True),
        Column("question_id", Integer),
        Column("user_id", Integer),
        Column("lifecycle_status", String),
        Column("status", String),
        Column("flow_stage", String),
        Column("round", Integer),
        Column("support_count_round", Integer),
        Column("support_count_total", Integer),
        Column("no_progress_count", Integer),
        Column("no_progress_help_request_count", Integer),
        Column("solution_exposed", Integer),
        Column("covered_points_current_round", JSON),
        Column("covered_points_all", JSON),
        Column("current_draft", Text),
        Column("last_support_draft", Text),
        Column("version", Integer),
    )
    explanation_attempts = Table(
        "explanation_attempts",
        source_metadata,
        Column("id", Integer, primary_key=True),
        Column("session_id", Integer),
        Column("round", Integer),
        Column("input_mode", String),
    )
    ai_evaluations = Table(
        "ai_evaluations",
        source_metadata,
        Column("id", Integer, primary_key=True),
        Column("session_id", Integer),
        Column("attempt_id", Integer),
        Column("prompt_version", String),
        Column("model_provider", String),
        Column("model_name", String),
        Column("validation_status", String),
        Column("validation_errors", JSON),
        Column("request_duration_ms", Integer),
    )
    source_metadata.create_all(source_engine)
    Base.metadata.create_all(target_engine)
    with source_engine.begin() as connection:
        connection.execute(
            insert(users),
            {
                "id": 1,
                "username": "teacher",
                "password_hash": "hash",
                "full_name": "教师",
                "role": "TEACHER",
            },
        )
        connection.execute(
            insert(questions),
            {
                "id": 1,
                "question_content": "历史题",
                "standard_answer": "答案",
                "rubric_points": ["评分点"],
                "common_errors": ["错误"],
                "alternative_solutions": ["方法"],
                "layered_hints": ["提示"],
                "guided_questions": [],
                "full_solution": "解析",
            },
        )
        connection.execute(
            insert(sessions),
            {
                "id": 1,
                "question_id": 1,
                "user_id": 1,
                "lifecycle_status": "active",
                "status": "IN_PROGRESS",
                "flow_stage": "WAIT_STUDENT_ACTION",
                "round": 1,
                "support_count_round": 0,
                "support_count_total": 0,
                "no_progress_count": 0,
                "no_progress_help_request_count": 0,
                "solution_exposed": False,
                "covered_points_current_round": [],
                "covered_points_all": [],
                "current_draft": "",
                "last_support_draft": "",
                "version": 0,
            },
        )
        connection.execute(
            insert(explanation_attempts),
            {"id": 1, "session_id": 1, "round": 1, "input_mode": "TEXT"},
        )
        connection.execute(
            insert(ai_evaluations),
            {
                "id": 1,
                "session_id": 1,
                "attempt_id": 1,
                "prompt_version": "v1",
                "model_provider": "test",
                "model_name": "test",
                "validation_status": "VALID",
                "validation_errors": [],
                "request_duration_ms": 1,
            },
        )

    result = migrate_legacy_sqlite(source_engine, target_engine)

    target_metadata = MetaData()
    target_metadata.reflect(bind=target_engine)
    with target_engine.connect() as connection:
        question = (
            connection.execute(select(target_metadata.tables["self_explain_questions"]))
            .mappings()
            .one()
        )
        session = connection.execute(select(target_metadata.tables["sessions"])).mappings().one()
        evaluation = (
            connection.execute(select(target_metadata.tables["ai_evaluations"])).mappings().one()
        )
    assert result.migrated_counts == {
        "users": 1,
        "self_explain_questions": 1,
        "sessions": 1,
        "explanation_attempts": 1,
        "ai_evaluations": 1,
    }
    assert question["id"] == 1
    assert question["tiku_question_id"] is None
    assert session["id"] == 1
    assert session["question_id"] == 1
    assert evaluation["evaluation_mode"] == "FULL_RUBRIC"
