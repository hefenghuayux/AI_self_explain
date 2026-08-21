from pathlib import Path

from alembic.config import Config
from conftest import authenticated_test_client
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from alembic import command
from app.models.session_event import SessionEvent
from app.schemas.model_request_snapshot import ModelRequestSnapshot
from app.services.ai_evaluation import AIModelClient, AIModelResponse


def question_payload() -> dict[str, object]:
    return {
        "questionContent": "计算 1 + 1。",
        "standardAnswer": "2",
        "rubricPoints": ["正确计算加法", "得出结果 2"],
        "commonErrors": ["把结果写成 3"],
        "alternativeSolutions": ["使用实物计数"],
        "layeredHints": ["先数一数两个数"],
        "guidedQuestions": ["两个 1 合起来是多少？"],
        "fullSolution": "1 加 1 等于 2。",
    }


def migrate_database(settings, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")


def create_started_session(client: TestClient) -> dict[str, object]:
    question = client.post("/api/questions", json=question_payload()).json()
    session = client.post("/api/sessions", json={"questionId": question["id"]}).json()
    choice = client.post(
        f"/api/sessions/{session['id']}/initial-choice",
        json={"choice": "KNOW", "version": session["version"]},
    )
    assert choice.status_code == 200
    return choice.json()


def test_text_self_explanation_writes_real_event_chain(settings, monkeypatch) -> None:
    def fake_evaluate(self, request: ModelRequestSnapshot) -> AIModelResponse:
        if request.purpose == "AI_SUPPORT":
            content = '{"content":"请补充最后的结果。","questions":[]}'
        else:
            content = (
                '{"correctness":"CORRECT","completeness":"COMPLETE",'
                '"coveredPoints":["正确计算加法","得出结果 2"],"missingPoints":[],'
                '"errorEvidence":[],"confidence":1,"needHumanReason":null}'
            )
        return AIModelResponse('{"choices":[]}', content, 3)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    migrate_database(settings, monkeypatch)
    with authenticated_test_client(settings) as client:
        started = create_started_session(client)
        response = client.post(
            f"/api/sessions/{started['id']}/text-attempts",
            json={"confirmedText": "1 加 1 等于 2。", "version": started["version"]},
        )
        assert response.status_code == 200

    engine = create_engine(settings.database_url)
    try:
        with OrmSession(engine) as database_session:
            events = list(
                database_session.scalars(
                    select(SessionEvent)
                    .where(SessionEvent.session_id == started["id"])
                    .order_by(SessionEvent.seq)
                )
            )
    finally:
        engine.dispose()

    assert [event.event_type for event in events] == [
        "session.started",
        "user.message",
        "state.changed",
        "context.added",
        "context.added",
        "context.added",
        "model.requested",
        "model.responded",
        "state.changed",
    ]
    run_events = [event for event in events if event.run_id is not None]
    assert {event.run_id for event in run_events} == {run_events[0].run_id}
    requested = next(event for event in events if event.event_type == "model.requested")
    responded = next(event for event in events if event.event_type == "model.responded")
    assert responded.parent_event_id == requested.event_id
    assert requested.data["messages"] == [
        {"role": "user", "content": requested.data["messages"][0]["content"]}
    ]
    assert responded.data["validation"] == "valid"
    state_events = [event for event in events if event.event_type == "state.changed"]
    assert state_events[-1].parent_event_id == responded.event_id
