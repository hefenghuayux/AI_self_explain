import json
from pathlib import Path

from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from alembic import command
from app.core.config import Settings
from app.main import create_app
from app.services.ai_evaluation import AIModelClient, AIModelResponse


def _question_payload() -> dict[str, object]:
    return {
        "questionContent": "计算 1 + 1。",
        "standardAnswer": "2",
        "rubricPoints": ["正确计算加法", "得出结果 2"],
        "commonErrors": ["把结果写成 3"],
        "alternativeSolutions": ["使用实物计数"],
        "layeredHints": ["先数一数两个数"],
        "fullSolution": "1 加 1 等于 2。",
    }


def _migrate_database(settings: Settings, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    alembic_config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.upgrade(alembic_config, "head")


def _client(settings: Settings, monkeypatch) -> TestClient:
    _migrate_database(settings, monkeypatch)
    return TestClient(create_app(settings))


def _create_session(client: TestClient) -> dict[str, object]:
    question = client.post("/api/questions", json=_question_payload())
    assert question.status_code == 201
    response = client.post("/api/sessions", json={"questionId": question.json()["id"]})
    assert response.status_code == 201
    return response.json()


def _stub_ai(monkeypatch, evaluation: dict[str, object]) -> None:
    def fake_evaluate(self, prompt: str, schema: dict[str, object]) -> AIModelResponse:
        if "教学支持生成器" in prompt:
            content = {"content": "请先重新检查加法结果。"}
        else:
            content = evaluation
        return AIModelResponse(raw_response="{}", content=json.dumps(content), duration_ms=1)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)


def test_not_know_generates_counted_hint_and_creates_audit_evidence(settings, monkeypatch) -> None:
    _stub_ai(monkeypatch, {})
    with _client(settings, monkeypatch) as client:
        session = _create_session(client)
        response = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "NOT_KNOW", "version": session["version"]},
        )

    assert response.status_code == 200
    saved = response.json()
    assert saved["flowStage"] == "WAIT_STUDENT_ACTION"
    assert saved["supportCountRound"] == 1
    assert saved["supportCountTotal"] == 1
    assert saved["latestSupport"]["supportType"] == "GIVE_HINT"

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            event = connection.execute(
                text("SELECT support_type, status FROM support_events")
            ).mappings().one()
            transition = connection.execute(
                text(
                    "SELECT after_snapshot FROM state_transition_events "
                    "WHERE trigger_type = 'SEND_GENERATED_HINT'"
                )
            ).scalar_one()
    finally:
        engine.dispose()
    assert dict(event) == {"support_type": "GIVE_HINT", "status": "VALID"}
    assert json.loads(transition)["supportCountTotal"] == 1


def test_first_and_second_round_limits_do_not_create_threshold_support_event(
    settings, monkeypatch
) -> None:
    _stub_ai(
        monkeypatch,
        {
            "correctness": "WRONG",
            "completeness": "INCOMPLETE",
            "coveredPoints": [],
            "missingPoints": ["正确计算加法", "得出结果 2"],
            "errorEvidence": [],
            "feedback": "请重新检查加法步骤。",
            "confidence": 1,
            "nextAction": "CORRECT_AND_ASK",
            "needHumanReason": None,
        },
    )
    with _client(settings, monkeypatch) as client:
        session = _create_session(client)
        client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "NOT_KNOW", "version": session["version"]},
        ).json()
        engine = create_engine(settings.database_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE sessions SET support_count_round = :round_count, "
                        "support_count_total = :total_count WHERE id = :session_id"
                    ),
                    {
                        "round_count": settings.first_round_support_limit - 1,
                        "total_count": settings.first_round_support_limit - 1,
                        "session_id": session["id"],
                    },
                )
        finally:
            engine.dispose()
        current = client.get(f"/api/sessions/{session['id']}").json()
        first_limit = client.post(
            f"/api/sessions/{session['id']}/request-support",
            json={"version": current["version"]},
        )

        assert first_limit.status_code == 200
        assert first_limit.json()["flowStage"] == "SHOWING_FULL_SOLUTION"
        assert first_limit.json()["supportCountRound"] == settings.first_round_support_limit
        second_round = client.post(
            f"/api/sessions/{session['id']}/full-solution-understanding",
            json={"understood": True, "version": first_limit.json()["version"]},
        ).json()
        engine = create_engine(settings.database_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE sessions SET support_count_round = :round_count "
                        "WHERE id = :session_id"
                    ),
                    {
                        "round_count": settings.second_round_support_limit - 1,
                        "session_id": session["id"],
                    },
                )
        finally:
            engine.dispose()
        second_limit = client.post(
            f"/api/sessions/{session['id']}/text-attempts",
            json={
                "confirmedText": "我还不会。",
                "version": second_round["version"],
            },
        )

    assert second_round["round"] == 2
    assert second_round["supportCountRound"] == 0
    assert second_round["coveredPointsCurrentRound"] == []
    assert second_limit.status_code == 200
    assert second_limit.json()["status"] == "STOPPED_LIMIT"
    assert second_limit.json()["supportCountTotal"] == settings.first_round_support_limit - 1

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            event_count = connection.execute(
                text("SELECT COUNT(*) FROM support_events")
            ).scalar_one()
    finally:
        engine.dispose()
    assert event_count == 1


def test_appeal_ends_automatic_flow_without_changing_support_count(settings, monkeypatch) -> None:
    evaluation = {
        "correctness": "CORRECT",
        "completeness": "INCOMPLETE",
        "coveredPoints": ["正确计算加法"],
        "missingPoints": ["得出结果 2"],
        "errorEvidence": [],
        "feedback": "请补充结果。",
        "confidence": 1,
        "nextAction": "ASK_FOCUSED_QUESTION",
        "needHumanReason": None,
    }
    _stub_ai(monkeypatch, evaluation)
    with _client(settings, monkeypatch) as client:
        session = _create_session(client)
        selected = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "KNOW", "version": session["version"]},
        ).json()
        evaluated = client.post(
            f"/api/sessions/{session['id']}/text-attempts",
            json={"confirmedText": "我先计算加法。", "version": selected["version"]},
        ).json()
        response = client.post(
            f"/api/sessions/{session['id']}/appeal",
            json={"reason": "我认为已经说明清楚。", "version": evaluated["version"]},
        )

    assert response.status_code == 200
    appealed = response.json()
    assert appealed["status"] == "NEED_HUMAN"
    assert appealed["needHumanReason"] == "学生申诉：我认为已经说明清楚。"
    assert appealed["supportCountRound"] == 0
    assert appealed["supportCountTotal"] == 0


def test_invalid_support_structure_is_recorded_and_ends_in_need_human(
    settings, monkeypatch
) -> None:
    def fake_evaluate(self, prompt: str, schema: dict[str, object]) -> AIModelResponse:
        return AIModelResponse(raw_response="{}", content="{}", duration_ms=1)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    with _client(settings, monkeypatch) as client:
        session = _create_session(client)
        response = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "NOT_KNOW", "version": session["version"]},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "NEED_HUMAN"
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            errors = connection.execute(
                text(
                    "SELECT error_type FROM external_call_records "
                    "WHERE call_type = 'AI_SUPPORT' ORDER BY id"
                )
            ).scalars().all()
    finally:
        engine.dispose()
    assert errors == ["AI_SCHEMA_ERROR"] * (settings.ai_schema_max_retries + 1)
