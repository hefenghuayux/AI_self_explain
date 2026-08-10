import json
from pathlib import Path

import pytest
from alembic.config import Config
from conftest import authenticated_test_client
from sqlalchemy import create_engine, text

from alembic import command
from app.services.ai_evaluation import AIModelClient, AIModelResponse


def complete_ai_response(request) -> AIModelResponse:
    return AIModelResponse(
        '{"choices": []}',
        '{"correctness":"CORRECT","completeness":"COMPLETE",'
        '"coveredPoints":["正确计算加法","得出结果 2"],"missingPoints":[],'
        '"errorEvidence":[],"confidence":1,"needHumanReason":null}',
        1,
    )


def focused_ai_response(request) -> AIModelResponse:
    if request.purpose == "AI_SUPPORT":
        return AIModelResponse(
            '{"choices": []}',
            '{"content":"请补充最终结果。","questions":'
            '[{"id":"teaching-q1","question":"最终结果是什么？"}]}',
            1,
        )
    return AIModelResponse(
        '{"choices": []}',
        '{"correctness":"CORRECT","completeness":"INCOMPLETE",'
        '"coveredPoints":["正确计算加法"],"missingPoints":["得出结果 2"],'
        '"errorEvidence":[],"confidence":1,"needHumanReason":null}',
        1,
    )


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
    return authenticated_test_client(settings)


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
        "WAIT_STUDENT_ACTION",
        "SHOWING_FULL_SOLUTION",
    ],
)
def test_pause_and_resume_preserve_stage_and_counters(settings, monkeypatch, flow_stage):
    with prepare_client(settings, monkeypatch) as client:
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
    with prepare_client(settings, monkeypatch) as client:
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
    monkeypatch.setattr(
        AIModelClient,
        "evaluate",
        lambda self, request: complete_ai_response(request),
    )
    with prepare_client(settings, monkeypatch) as client:
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
    monkeypatch.setattr(
        AIModelClient,
        "evaluate",
        lambda self, request: complete_ai_response(request),
    )
    with prepare_client(settings, monkeypatch) as client:
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


def test_text_submission_trace_uses_v3_merged_event(settings, monkeypatch):
    monkeypatch.setattr(
        AIModelClient,
        "evaluate",
        lambda self, request: complete_ai_response(request),
    )
    with prepare_client(settings, monkeypatch) as client:
        session = create_session(client)
        chosen = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "KNOW", "version": session["version"]},
        ).json()
        response = client.post(
            f"/api/sessions/{session['id']}/text-attempts",
            json={"confirmedText": "1 加 1 等于 2。", "version": chosen["version"]},
            headers={"X-Request-ID": "submission-request"},
        )
        trace = client.get(f"/api/sessions/{session['id']}/audit/trace")

    assert response.status_code == 200
    assert trace.status_code == 200
    trace_body = trace.json()
    assert trace_body["schemaVersion"] == "3.0"
    assert trace_body["producer"] == {
        "service": "ai-self-explain-backend",
        "version": "0.1.0",
    }
    submitted = [
        event
        for event in trace_body["events"]
        if event["eventName"] == "student.explanation.submitted"
    ]
    assert len(submitted) == 1
    assert not any(
        event["eventName"] == "student.input.confirmed"
        for event in trace_body["events"]
    )
    assert submitted[0]["correlation"]["requestId"] == "submission-request"
    assert set(submitted[0]["references"]) >= {"attemptId", "studentSubmissionId"}
    assert submitted[0]["data"]["content"]["characterCount"] == len("1 加 1 等于 2。")
    assert "source" not in submitted[0]
    assert "schemaVersion" not in submitted[0]


def test_support_trace_persists_request_and_transition_correlation(settings, monkeypatch):
    monkeypatch.setattr(
        AIModelClient,
        "evaluate",
        lambda self, request: focused_ai_response(request),
    )
    with prepare_client(settings, monkeypatch) as client:
        session = create_session(client)
        chosen = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "KNOW", "version": session["version"]},
        ).json()
        response = client.post(
            f"/api/sessions/{session['id']}/text-attempts",
            json={"confirmedText": "1 加 1 还需要写结果。", "version": chosen["version"]},
            headers={"X-Request-ID": "support-request"},
        )
        trace = client.get(f"/api/sessions/{session['id']}/audit/trace")

    assert response.status_code == 200
    support_event = next(
        event for event in trace.json()["events"] if event["eventName"] == "support.generated"
    )
    transition_event = next(
        event
        for event in trace.json()["events"]
        if event["operation"]["name"] == "APPLY_AI_EVALUATION"
    )
    assert support_event["correlation"]["requestId"] == "support-request"
    assert transition_event["correlation"]["requestId"] == "support-request"
    assert transition_event["references"]["supportEventId"] == support_event["references"][
        "supportEventId"
    ]


def test_unified_trace_is_json_and_exported_to_files(settings, monkeypatch):
    with prepare_client(settings, monkeypatch) as client:
        session = create_session(client)
        pause = client.post(
            f"/api/sessions/{session['id']}/pause",
            json={"version": session["version"]},
            headers={"X-Request-ID": "trace-request"},
        )
        session_dir = settings.audit_export_dir / str(session["id"])
        for path in (session_dir / "trace.jsonl", session_dir / "audit.md"):
            if path.exists():
                path.unlink()
        trace = client.get(f"/api/sessions/{session['id']}/audit/trace")
        assert not (session_dir / "trace.jsonl").exists()
        assert not (session_dir / "audit.md").exists()
        export = client.post(f"/api/sessions/{session['id']}/audit/export")

    assert pause.status_code == 200
    assert trace.status_code == 200
    trace_body = trace.json()
    assert trace_body["sessionId"] == session["id"]
    assert trace_body["summary"]["eventCount"] >= 2
    assert {item["eventName"] for item in trace_body["events"]} >= {
        "session.created",
        "state.transitioned",
    }
    assert export.status_code == 200
    export_body = export.json()
    jsonl_path = Path(export_body["jsonlPath"])
    markdown_path = Path(export_body["markdownPath"])
    assert jsonl_path.exists()
    assert markdown_path.exists()
    jsonl_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(jsonl_lines) >= 2
    envelopes = [json.loads(line) for line in jsonl_lines]
    assert all(envelope["schemaVersion"] == "3.0" for envelope in envelopes)
    assert all("event" in envelope for envelope in envelopes)
    assert all("schemaVersion" not in envelope["event"] for envelope in envelopes)
    assert all("source" not in envelope["event"] for envelope in envelopes)
    assert "# 会话审计报告" in markdown_path.read_text(encoding="utf-8")


def test_business_trace_endpoint_returns_deterministic_steps(settings, monkeypatch):
    with prepare_client(settings, monkeypatch) as client:
        session = create_session(client)
        response = client.get(f"/api/sessions/{session['id']}/audit/business-trace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sessionId"] == session["id"]
    assert payload["steps"]
    assert all(step["eventIds"] for step in payload["steps"])
    assert all(step["events"] for step in payload["steps"])
