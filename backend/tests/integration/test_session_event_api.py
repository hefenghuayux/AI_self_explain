from pathlib import Path

from alembic.config import Config
from conftest import authenticated_test_client
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession

from alembic import command
from app.core.config import Settings
from app.services.event_store import EventStore


def migrate_database(settings: Settings, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")


def question_payload() -> dict[str, object]:
    return {
        "questionContent": "计算 1 + 1。",
        "standardAnswer": "2",
        "rubricPoints": ["列出加法过程"],
        "commonErrors": ["把结果写成 3"],
        "alternativeSolutions": ["使用实物计数"],
        "layeredHints": ["先数一数两个数"],
        "guidedQuestions": [],
        "fullSolution": "1 加 1 等于 2。",
    }


def prepare_client(settings: Settings, monkeypatch) -> TestClient:
    migrate_database(settings, monkeypatch)
    return authenticated_test_client(settings)


def append_run(settings: Settings, session_id: int) -> None:
    engine = create_engine(settings.database_url)
    try:
        with OrmSession(engine) as database_session:
            store = EventStore(database_session)
            run_id = "run_api_1"
            user = store.append(
                session_id,
                "user.message",
                {"text": "1 加 1 等于 2。", "inputType": "text"},
                run_id=run_id,
            )
            context = store.append(
                session_id,
                "context.added",
                {"kind": "question", "source": "question:1", "content": "计算 1 + 1。"},
                run_id=run_id,
                parent_event_id=user.event_id,
            )
            requested = store.append(
                session_id,
                "model.requested",
                {
                    "provider": "test-ai",
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "请评价"}],
                    "surfaceSeq": context.seq,
                },
                run_id=run_id,
                parent_event_id=user.event_id,
            )
            responded = store.append(
                session_id,
                "model.responded",
                {
                    "output": {"correctness": "CORRECT"},
                    "rawContent": '{"correctness": "CORRECT"}',
                    "validation": "valid",
                    "durationMs": 3,
                },
                run_id=run_id,
                parent_event_id=requested.event_id,
            )
            store.append(
                session_id,
                "state.changed",
                {"from": "AI_EVALUATING", "to": "WAIT_STUDENT_ACTION", "reason": "done"},
                run_id=run_id,
                parent_event_id=responded.event_id,
            )
            database_session.commit()
    finally:
        engine.dispose()


def test_session_event_projection_apis(settings, monkeypatch) -> None:
    with prepare_client(settings, monkeypatch) as client:
        question = client.post("/api/questions", json=question_payload())
        assert question.status_code == 201
        created = client.post("/api/sessions", json={"questionId": question.json()["id"]})
        assert created.status_code == 201
        session_id = created.json()["id"]
        append_run(settings, session_id)
        events = client.get(f"/api/sessions/{session_id}/events", params={"limit": 2})
        page = client.get(
            f"/api/sessions/{session_id}/events", params={"afterSeq": 1, "limit": 500}
        )
        event = client.get(f"/api/sessions/{session_id}/events/3")
        surface = client.get(f"/api/sessions/{session_id}/surface")
        historical_surface = client.get(
            f"/api/sessions/{session_id}/surface", params={"asOfSeq": 1}
        )
        trajectory = client.get(f"/api/sessions/{session_id}/trajectory")
        trace = client.get(f"/api/sessions/{session_id}/trace", params={"run_id": "run_api_1"})

    assert events.status_code == 200
    assert [item["seq"] for item in events.json()["events"]] == [0, 1]
    assert events.json()["nextAfterSeq"] == 1
    assert [item["seq"] for item in page.json()["events"]] == [2, 3, 4, 5]
    assert event.json()["eventType"] == "model.requested"
    assert surface.json()["messages"][0]["content"] == "1 加 1 等于 2。"
    assert surface.json()["contexts"][0]["source"] == "question:1"
    assert page.json()["events"][2]["data"]["rawContent"] == '{"correctness": "CORRECT"}'
    assert historical_surface.json()["messages"][0]["seq"] == 1
    assert historical_surface.json()["contexts"] == []
    steps = trajectory.json()["runs"][0]["steps"]
    assert [step["kind"] for step in steps] == ["user_input", "model_call", "state_change"]
    assert steps[1]["status"] == "success"
    records = trajectory.json()["runs"][0]["records"]
    assert [record["kind"] for record in records] == [
        "user",
        "context",
        "model_request",
        "model_response",
        "state_change",
    ]
    assert [record["index"] for record in records] == [1, 2, 3, 4, 5]
    assert records[0]["summary"] == "1 加 1 等于 2。"
    assert records[1]["summary"] == "question · question:1 · 计算 1 + 1。"
    assert records[2]["status"] == "complete"
    assert records[2]["detail"]["modelRequest"]["surfaceSeq"] == 2
    assert records[3]["status"] == "complete"
    assert records[3]["durationMs"] == 3
    assert records[3]["detail"]["modelResponse"]["output"] == {"correctness": "CORRECT"}
    assert records[4]["summary"] == "AI_EVALUATING → WAIT_STUDENT_ACTION"
    session_events = trajectory.json()["events"]
    assert [record["eventSeq"] for record in session_events] == [0, 1, 2, 3, 4, 5]
    assert session_events[0]["kind"] == "session"
    roots = trace.json()["roots"]
    assert roots[0]["eventType"] == "user.message"
    assert roots[0]["children"][1]["eventType"] == "model.requested"


def test_session_event_api_returns_contract_errors(settings, monkeypatch) -> None:
    with prepare_client(settings, monkeypatch) as client:
        question = client.post("/api/questions", json=question_payload())
        assert question.status_code == 201
        created = client.post("/api/sessions", json={"questionId": question.json()["id"]})
        assert created.status_code == 201
        session_id = created.json()["id"]
        missing_session = client.get("/api/sessions/99999/events")
        missing_event = client.get(f"/api/sessions/{session_id}/events/99999")
        invalid_limit = client.get(f"/api/sessions/{session_id}/events", params={"limit": 501})

    assert missing_session.status_code == 404
    assert missing_session.json()["detail"] == "SESSION_NOT_FOUND"
    assert missing_event.status_code == 404
    assert missing_event.json()["detail"] == "EVENT_NOT_FOUND"
    assert invalid_limit.status_code == 422
