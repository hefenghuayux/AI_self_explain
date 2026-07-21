import json
from pathlib import Path

from alembic.config import Config
from fastapi.testclient import TestClient
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
        "layeredHints": ["先数一数两个数", "再合并两组数量"],
        "guidedQuestions": ["两个 1 合起来是多少？"],
        "fullSolution": "1 加 1 等于 2。",
    }


def migrate_database(settings, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")


def prepare_client(settings, monkeypatch) -> TestClient:
    migrate_database(settings, monkeypatch)
    return TestClient(create_app(settings))


def create_started_session(client: TestClient) -> dict[str, object]:
    question_response = client.post("/api/questions", json=question_payload())
    assert question_response.status_code == 201
    session_response = client.post(
        "/api/sessions", json={"questionId": question_response.json()["id"]}
    )
    assert session_response.status_code == 201
    session = session_response.json()
    choice_response = client.post(
        f"/api/sessions/{session['id']}/initial-choice",
        json={"choice": "KNOW", "version": session["version"]},
    )
    assert choice_response.status_code == 200
    return choice_response.json()


def test_timeline_persists_visible_feedback_and_hides_structured_details(
    settings, monkeypatch
) -> None:
    def fake_evaluate(self, prompt: str, schema: dict[str, object]) -> AIModelResponse:
        return AIModelResponse(
            "{\"choices\": []}",
            json.dumps(
                {
                    "correctness": "WRONG",
                    "completeness": "INCOMPLETE",
                    "coveredPoints": ["正确计算加法"],
                    "missingPoints": ["得出结果 2"],
                    "errorEvidence": [],
                    "feedback": "请重新检查你得出的结果。",
                    "confidence": 1,
                    "nextAction": "CORRECT_AND_ASK",
                    "needHumanReason": None,
                }
            ),
            8,
        )

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    with prepare_client(settings, monkeypatch) as client:
        started_session = create_started_session(client)
        evaluation_response = client.post(
            f"/api/sessions/{started_session['id']}/text-attempts",
            json={"confirmedText": "1 加 1 等于 3。", "version": started_session["version"]},
        )
        assert evaluation_response.status_code == 200
        first_timeline = client.get(f"/api/sessions/{started_session['id']}/timeline")
        second_timeline = client.get(f"/api/sessions/{started_session['id']}/timeline")
        appeal_response = client.post(
            f"/api/sessions/{started_session['id']}/appeal",
            json={"reason": "我想再说明一次。", "version": evaluation_response.json()["version"]},
        )
        assert appeal_response.status_code == 200
        appealed_timeline = client.get(f"/api/sessions/{started_session['id']}/timeline")

    assert first_timeline.status_code == 200
    assert first_timeline.json() == second_timeline.json()
    assert first_timeline.json() == [
        {
            "id": "evaluation-1",
            "eventType": "EVALUATION",
            "content": "请重新检查你得出的结果。",
            "correctness": "WRONG",
            "completeness": "INCOMPLETE",
            "action": "CORRECT_AND_ASK",
            "createdAt": first_timeline.json()[0]["createdAt"],
        }
    ]
    assert "coveredPoints" not in first_timeline.json()[0]
    assert appealed_timeline.status_code == 200
    assert appealed_timeline.json()[-1]["eventType"] == "NEED_HUMAN"
    assert appealed_timeline.json()[-1]["content"] == "已提交不同意 AI 判断的申诉，已转人工帮助。"


def test_timeline_records_solution_display_without_revealing_solution_content(
    settings, monkeypatch
) -> None:
    with prepare_client(settings, monkeypatch) as client:
        started_session = create_started_session(client)
        engine = create_engine(settings.database_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE sessions SET flow_stage = 'WAIT_STUDENT_ACTION', "
                        "support_count_round = :support_count WHERE id = :session_id"
                    ),
                    {
                        "support_count": settings.first_round_support_limit - 1,
                        "session_id": started_session["id"],
                    },
                )
        finally:
            engine.dispose()
        limit_response = client.post(
            f"/api/sessions/{started_session['id']}/request-support",
            json={"mainDraft": "我还没有新的思路。", "version": started_session["version"]},
        )
        timeline_response = client.get(f"/api/sessions/{started_session['id']}/timeline")

    assert limit_response.status_code == 200
    assert limit_response.json()["flowStage"] == "SHOWING_FULL_SOLUTION"
    assert timeline_response.status_code == 200
    assert timeline_response.json() == [
        {
            "id": "solution-3",
            "eventType": "FULL_SOLUTION",
            "content": "已展示完整解析。",
            "correctness": None,
            "completeness": None,
            "action": None,
            "createdAt": timeline_response.json()[0]["createdAt"],
        }
    ]
