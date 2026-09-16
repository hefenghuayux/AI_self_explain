from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session as DatabaseSession

from alembic import command
from app.core.config import Settings
from app.core.database import create_database_engine
from app.models.question import Question
from app.models.session import Session
from app.models.session_event import SessionEvent
from app.models.user import User
from app.repositories.sessions import SessionRepository
from app.services.event_store import EventStore, InvalidEventDataError


def migrate_database(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    alembic_config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.upgrade(alembic_config, "head")


def create_question(database_session: DatabaseSession) -> Question:
    question = Question(
        question_content="计算 1 + 1。",
        standard_answer="2",
        rubric_points=["正确计算"],
        common_errors=["结果写成 3"],
        alternative_solutions=["计数"],
        layered_hints=["先数数"],
        guided_questions=["结果是多少？"],
        full_solution="1 加 1 等于 2。",
    )
    database_session.add(question)
    database_session.commit()
    database_session.refresh(question)
    return question


def create_learning_session(database_session: DatabaseSession) -> Session:
    question = create_question(database_session)
    user = User(
        username="event-store-user",
        password_hash="test-password-hash",
        full_name="事件存储测试用户",
        role="TEACHER",
    )
    database_session.add(user)
    database_session.commit()
    database_session.refresh(user)
    return SessionRepository(database_session).create(question.id, user.id)


def test_migration_creates_event_constraints_and_indexes(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrate_database(settings, monkeypatch)
    engine = create_engine(settings.database_url)
    try:
        inspector = inspect(engine)
        unique_constraints = {
            constraint["name"] for constraint in inspector.get_unique_constraints("session_events")
        }
        indexes = {index["name"] for index in inspector.get_indexes("session_events")}
        session_columns = {column["name"] for column in inspector.get_columns("sessions")}
    finally:
        engine.dispose()

    assert unique_constraints == {
        "uq_session_events_event_id",
        "uq_session_events_session_seq",
    }
    assert indexes == {
        "ix_session_events_session_id_seq",
        "ix_session_events_session_run_seq",
        "ix_session_events_session_type_seq",
    }
    assert {"parent_id", "lifecycle_status", "user_id"} <= session_columns


def test_migration_backfills_started_event_for_existing_session(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    alembic_config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.upgrade(alembic_config, "20260810_17")

    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO questions ("
                    "id, question_content, standard_answer, rubric_points, common_errors, "
                    "alternative_solutions, layered_hints, full_solution, guided_questions"
                    ") VALUES (1, '题目', '答案', '[]', '[]', '[]', '[]', '解析', '[]')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO sessions ("
                    "id, question_id, status, flow_stage, round, support_count_round, "
                    "support_count_total, no_progress_count, solution_exposed, "
                    "covered_points_current_round, covered_points_all, version"
                    ") VALUES (1, 1, 'COMPLETED', 'WAIT_STUDENT_ACTION', 1, 0, 0, 0, 0, "
                    "'[]', '[]', 1)"
                )
            )
            created_at = connection.execute(
                text("SELECT created_at FROM sessions WHERE id = 1")
            ).scalar_one()

        command.upgrade(alembic_config, "head")

        with engine.connect() as connection:
            event = connection.execute(
                text(
                    "SELECT seq, event_id, event_type, occurred_at, data "
                    "FROM session_events WHERE session_id = 1"
                )
            ).one()
            lifecycle_status = connection.execute(
                text("SELECT lifecycle_status FROM sessions WHERE id = 1")
            ).scalar_one()
    finally:
        engine.dispose()

    assert tuple(event) == (
        0,
        "evt_migrated_session_1_started",
        "session.started",
        created_at,
        "{}",
    )
    assert lifecycle_status == "completed"


def test_create_session_appends_started_as_seq_zero(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrate_database(settings, monkeypatch)
    engine = create_database_engine(settings)
    try:
        with DatabaseSession(engine) as database_session:
            learning_session = create_learning_session(database_session)
            events = EventStore(database_session).list_events(learning_session.id)
    finally:
        engine.dispose()

    assert learning_session.lifecycle_status == "active"
    assert [(event.seq, event.event_type, event.data) for event in events] == [
        (0, "session.started", {})
    ]


def test_append_validates_parent_payload_and_sequence(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrate_database(settings, monkeypatch)
    engine = create_database_engine(settings)
    try:
        with DatabaseSession(engine) as database_session:
            learning_session = create_learning_session(database_session)
            store = EventStore(database_session)
            user_event = store.append(
                learning_session.id,
                "user.message",
                {"text": "我的答案是 2", "inputType": "text"},
                run_id="run_1",
            )
            requested = store.append(
                learning_session.id,
                "model.requested",
                {
                    "provider": "test-ai",
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "评价答案"}],
                    "surfaceSeq": user_event.seq,
                },
                run_id="run_1",
                parent_event_id=user_event.event_id,
            )
            database_session.commit()

            with pytest.raises(InvalidEventDataError, match="父事件"):
                store.append(
                    learning_session.id,
                    "state.changed",
                    {"from": "A", "to": "B", "reason": "test"},
                    parent_event_id="evt_missing",
                )
            database_session.rollback()
            events = store.list_events(learning_session.id)
            page = store.list_events(learning_session.id, after_seq=0, limit=1)
            fetched = store.get_event(learning_session.id, requested.seq)
    finally:
        engine.dispose()

    assert [event.seq for event in events] == [0, 1, 2]
    assert requested.parent_event_id == user_event.event_id
    assert [event.seq for event in page] == [1]
    assert fetched.event_id == requested.event_id


@pytest.mark.parametrize(
    ("event_type", "data", "message"),
    [
        ("unknown.event", {}, "不支持的事件类型"),
        ("user.message", [], "必须是 JSON object"),
        ("user.message", {"text": "答案"}, "data 校验失败"),
    ],
)
def test_append_rejects_invalid_event_data(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
    data: object,
    message: str,
) -> None:
    migrate_database(settings, monkeypatch)
    engine = create_database_engine(settings)
    try:
        with DatabaseSession(engine) as database_session:
            learning_session = create_learning_session(database_session)
            with pytest.raises(InvalidEventDataError, match=message):
                EventStore(database_session).append(learning_session.id, event_type, data)  # type: ignore[arg-type]
            database_session.rollback()
    finally:
        engine.dispose()


def test_business_fact_and_event_roll_back_together(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrate_database(settings, monkeypatch)
    engine = create_database_engine(settings)
    try:
        with DatabaseSession(engine) as database_session:
            learning_session = create_learning_session(database_session)
            session_id = learning_session.id
            learning_session.current_draft = "不应保存"
            EventStore(database_session).append(
                learning_session.id,
                "user.message",
                {"text": "不应保存", "inputType": "text"},
                run_id="run_rollback",
            )
            database_session.rollback()

        with DatabaseSession(engine) as database_session:
            saved_session = database_session.get(Session, session_id)
            events = EventStore(database_session).list_events(session_id)
    finally:
        engine.dispose()

    assert saved_session is not None
    assert saved_session.current_draft == ""
    assert [event.event_type for event in events] == ["session.started"]


def test_concurrent_appends_use_distinct_continuous_sequences(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrate_database(settings, monkeypatch)
    engine = create_database_engine(settings)
    try:
        with DatabaseSession(engine) as database_session:
            session_id = create_learning_session(database_session).id

        barrier = Barrier(2)

        def append_message(index: int) -> None:
            with DatabaseSession(engine) as database_session:
                barrier.wait()
                EventStore(database_session).append(
                    session_id,
                    "user.message",
                    {"text": f"答案 {index}", "inputType": "text"},
                    run_id=f"run_{index}",
                )
                database_session.commit()

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(append_message, (1, 2)))

        with DatabaseSession(engine) as database_session:
            events = list(
                database_session.scalars(
                    select(SessionEvent)
                    .where(SessionEvent.session_id == session_id)
                    .order_by(SessionEvent.seq)
                )
            )
    finally:
        engine.dispose()

    assert [event.seq for event in events] == [0, 1, 2]
