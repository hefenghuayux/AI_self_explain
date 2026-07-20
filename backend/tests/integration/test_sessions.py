import json
from pathlib import Path

from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.core.config import Settings
from app.main import create_app


def question_payload() -> dict[str, object]:
    return {
        "questionContent": "计算 1 + 1。",
        "standardAnswer": "2",
        "rubricPoints": ["正确计算加法", "得出结果 2"],
        "commonErrors": ["把结果写成 3"],
        "alternativeSolutions": ["使用实物计数"],
        "layeredHints": ["先数一数两个数", "再合并两组数量"],
        "fullSolution": "1 加 1 等于 2。",
    }


def migrate_database(settings: Settings, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    alembic_config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.upgrade(alembic_config, "head")


def create_question(client: TestClient) -> int:
    response = client.post("/api/questions", json=question_payload())
    assert response.status_code == 201
    return response.json()["id"]


def create_session(client: TestClient, question_id: int) -> dict[str, object]:
    response = client.post("/api/sessions", json={"questionId": question_id})
    assert response.status_code == 201
    return response.json()


def prepare_client(settings: Settings, monkeypatch) -> TestClient:
    migrate_database(settings, monkeypatch)
    return TestClient(create_app(settings))


def test_migration_creates_session_tables(settings: Settings, monkeypatch) -> None:
    migrate_database(settings, monkeypatch)
    engine = create_engine(settings.database_url)
    try:
        inspector = inspect(engine)
        assert inspector.has_table("sessions")
        assert inspector.has_table("explanation_attempts")
        assert inspector.has_table("state_transition_events")
    finally:
        engine.dispose()


def test_new_session_has_initial_state_and_audit_event(settings: Settings, monkeypatch) -> None:
    with prepare_client(settings, monkeypatch) as client:
        session = create_session(client, create_question(client))

    assert session["status"] == "IN_PROGRESS"
    assert session["flowStage"] == "WAIT_INITIAL_CHOICE"
    assert session["round"] == 1
    assert session["version"] == 0

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            event = (
                connection.execute(
                    text(
                        "SELECT trigger_type, from_status, to_status, to_flow_stage "
                        "FROM state_transition_events"
                    )
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()
    assert dict(event) == {
        "trigger_type": "CREATE_SESSION",
        "from_status": "NEW",
        "to_status": "IN_PROGRESS",
        "to_flow_stage": "WAIT_INITIAL_CHOICE",
    }


def test_archived_question_cannot_create_session(settings: Settings, monkeypatch) -> None:
    with prepare_client(settings, monkeypatch) as client:
        question_id = create_question(client)
        archive_response = client.post(f"/api/questions/{question_id}/archive")
        assert archive_response.status_code == 200
        response = client.post("/api/sessions", json={"questionId": question_id})

    assert response.status_code == 409
    assert response.json()["detail"] == "已归档题目不能创建会话"


def test_know_choice_opens_text_input_and_text_is_saved(settings: Settings, monkeypatch) -> None:
    with prepare_client(settings, monkeypatch) as client:
        session = create_session(client, create_question(client))
        choice_response = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "KNOW", "version": session["version"]},
        )
        assert choice_response.status_code == 200
        chosen = choice_response.json()
        assert chosen["flowStage"] == "CAPTURING_INPUT"
        assert chosen["version"] == 1

        submit_response = client.post(
            f"/api/sessions/{session['id']}/text-attempts",
            json={"confirmedText": "1 加 1 等于 2。", "version": chosen["version"]},
        )

    assert submit_response.status_code == 200
    submitted = submit_response.json()
    assert submitted["flowStage"] == "AI_EVALUATING"
    assert submitted["version"] == 2

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            attempt = (
                connection.execute(
                    text("SELECT input_mode, confirmed_text FROM explanation_attempts")
                )
                .mappings()
                .one()
            )
            event = (
                connection.execute(
                    text(
                        "SELECT trigger_type, related_attempt_id, before_snapshot, after_snapshot "
                        "FROM state_transition_events WHERE trigger_type = 'SUBMIT_TEXT'"
                    )
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()
    assert dict(attempt) == {"input_mode": "TEXT", "confirmed_text": "1 加 1 等于 2。"}
    assert event["related_attempt_id"] is not None
    assert json.loads(event["before_snapshot"])["flowStage"] == "CAPTURING_INPUT"
    assert json.loads(event["after_snapshot"])["flowStage"] == "AI_EVALUATING"


def test_not_know_choice_is_saved_at_the_stage_five_entry_point(
    settings: Settings, monkeypatch
) -> None:
    with prepare_client(settings, monkeypatch) as client:
        session = create_session(client, create_question(client))
        response = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "NOT_KNOW", "version": session["version"]},
        )

    assert response.status_code == 200
    assert response.json()["initialChoice"] == "NOT_KNOW"
    assert response.json()["flowStage"] == "WAIT_STUDENT_ACTION"


def test_blank_text_does_not_create_attempt_or_change_stage(
    settings: Settings, monkeypatch
) -> None:
    with prepare_client(settings, monkeypatch) as client:
        session = create_session(client, create_question(client))
        chosen = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "KNOW", "version": session["version"]},
        ).json()
        response = client.post(
            f"/api/sessions/{session['id']}/text-attempts",
            json={"confirmedText": "   ", "version": chosen["version"]},
        )
        current = client.get(f"/api/sessions/{session['id']}").json()

    assert response.status_code == 422
    assert current["flowStage"] == "CAPTURING_INPUT"
    assert current["version"] == 1
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            count = connection.execute(
                text("SELECT COUNT(*) FROM explanation_attempts")
            ).scalar_one()
    finally:
        engine.dispose()
    assert count == 0


def test_illegal_stage_and_duplicate_operation_are_rejected(
    settings: Settings, monkeypatch
) -> None:
    with prepare_client(settings, monkeypatch) as client:
        session = create_session(client, create_question(client))
        illegal_response = client.post(
            f"/api/sessions/{session['id']}/text-attempts",
            json={"confirmedText": "直接提交", "version": 0},
        )
        assert illegal_response.status_code == 409
        assert "当前流程阶段" in illegal_response.json()["detail"]

        first_choice = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "KNOW", "version": 0},
        )
        assert first_choice.status_code == 200
        duplicate_response = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "KNOW", "version": 0},
        )

    assert duplicate_response.status_code == 409
    assert "会话版本已变化" in duplicate_response.json()["detail"]


def test_terminal_session_cannot_continue_automatic_flow(settings: Settings, monkeypatch) -> None:
    with prepare_client(settings, monkeypatch) as client:
        session = create_session(client, create_question(client))
        engine = create_engine(settings.database_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE sessions SET status = 'COMPLETED' WHERE id = :session_id"),
                    {"session_id": session["id"]},
                )
        finally:
            engine.dispose()
        response = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "KNOW", "version": session["version"]},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "终态会话不能继续操作：COMPLETED"
