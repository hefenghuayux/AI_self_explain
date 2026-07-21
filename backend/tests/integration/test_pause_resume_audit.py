from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from app.main import create_app
from app.services.ai_evaluation import AIModelClient, AIModelResponse


def question_payload() -> dict[str, object]:
    return {
        "questionContent": "计算 1 + 1。",
        "standardAnswer": "2",
        "rubricPoints": ["正确计算加法", "得出结果 2"],
        "commonErrors": ["把结果写成 3"],
        "alternativeSolutions": ["使用实物计数"],
        "layeredHints": ["先数一数两个数"],
        "guidedQuestions": [],
        "fullSolution": "1 加 1 等于 2。",
    }


def migrate_database(settings, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")


def prepare_client(settings, monkeypatch):
    migrate_database(settings, monkeypatch)
    return create_app(settings)


def create_session(client) -> dict[str, object]:
    question_response = client.post("/api/questions", json=question_payload())
    assert question_response.status_code == 201, question_response.text
    question = question_response.json()
    session_response = client.post("/api/sessions", json={"questionId": question["id"]})
    assert session_response.status_code == 201, session_response.text
    return session_response.json()


@pytest.mark.parametrize(
    "flow_stage",
    [
        "WAIT_INITIAL_CHOICE",
        "CAPTURING_INPUT",
        "CONFIRMING_TEXT",
        "WAIT_STUDENT_ACTION",
        "SHOWING_FULL_SOLUTION",
    ],
)
def test_pause_and_resume_preserve_stage_and_counters(settings, monkeypatch, flow_stage):
    from fastapi.testclient import TestClient

    with TestClient(prepare_client(settings, monkeypatch)) as client:
        session = create_session(client)
        engine = create_engine(settings.database_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE sessions SET flow_stage = :flow_stage, round = 2, "
                        "support_count_round = 1, support_count_total = 4 WHERE id = :id"
                    ),
                    {"flow_stage": flow_stage, "id": session["id"]},
                )
        finally:
            engine.dispose()
        paused = client.post(
            f"/api/sessions/{session['id']}/pause",
            json={"version": session["version"]},
            headers={"X-Request-ID": "pause-request"},
        )
        resumed = client.post(
            f"/api/sessions/{session['id']}/resume",
            json={"version": paused.json()["version"]},
            headers={"X-Request-ID": "resume-request"},
        )

    assert paused.status_code == 200
    assert paused.headers["X-Request-ID"] == "pause-request"
    assert paused.json()["status"] == "PAUSED"
    assert paused.json()["pausedFromStage"] == flow_stage
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "IN_PROGRESS"
    assert resumed.json()["flowStage"] == flow_stage
    assert resumed.json()["round"] == 2
    assert resumed.json()["supportCountRound"] == 1
    assert resumed.json()["supportCountTotal"] == 4


def test_processing_stage_cannot_pause(settings, monkeypatch):
    from fastapi.testclient import TestClient

    with TestClient(prepare_client(settings, monkeypatch)) as client:
        session = create_session(client)
        engine = create_engine(settings.database_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE sessions SET flow_stage = 'AI_EVALUATING' WHERE id = :id"),
                    {"id": session["id"]},
                )
        finally:
            engine.dispose()
        response = client.post(
            f"/api/sessions/{session['id']}/pause",
            json={"version": session["version"]},
        )

    assert response.status_code == 409
    assert "当前流程阶段不能暂停" in response.json()["detail"]


def test_audit_state_events_include_request_id(settings, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        AIModelClient,
        "evaluate",
        lambda self, prompt, schema: AIModelResponse(
            '{"choices": []}',
            '{"correctness":"CORRECT","completeness":"COMPLETE",'
            '"coveredPoints":["正确计算加法","得出结果 2"],"missingPoints":[],'
            '"errorEvidence":[],"feedback":"完成。","confidence":1,'
            '"nextAction":"COMPLETE","needHumanReason":null}',
            1,
        ),
    )
    with TestClient(prepare_client(settings, monkeypatch)) as client:
        session = create_session(client)
        response = client.post(
            f"/api/sessions/{session['id']}/pause",
            json={"version": session["version"]},
            headers={"X-Request-ID": "audit-request"},
        )
        audit = client.get(f"/api/sessions/{session['id']}/audit/state-events")

    assert response.status_code == 200
    assert audit.status_code == 200
    pause_event = [item for item in audit.json() if item["triggerType"] == "PAUSE_SESSION"][0]
    assert pause_event["requestId"] == "audit-request"


def test_external_call_audit_includes_request_id(settings, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        AIModelClient,
        "evaluate",
        lambda self, prompt, schema: AIModelResponse(
            '{"choices": []}',
            '{"correctness":"CORRECT","completeness":"COMPLETE",'
            '"coveredPoints":["正确计算加法","得出结果 2"],"missingPoints":[],'
            '"errorEvidence":[],"feedback":"完成。","confidence":1,'
            '"nextAction":"COMPLETE","needHumanReason":null}',
            1,
        ),
    )
    with TestClient(prepare_client(settings, monkeypatch)) as client:
        session = create_session(client)
        chosen = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "KNOW", "version": session["version"]},
        ).json()
        response = client.post(
            f"/api/sessions/{session['id']}/text-attempts",
            json={"confirmedText": "1 加 1 等于 2。", "version": chosen["version"]},
            headers={"X-Request-ID": "ai-request"},
        )
        audit = client.get(f"/api/sessions/{session['id']}/audit/external-calls")

    assert response.status_code == 200
    assert audit.status_code == 200
    assert audit.json()[0]["requestId"] == "ai-request"
