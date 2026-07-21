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
        "guidedQuestions": ["两个 1 合起来是多少？"],
        "fullSolution": "1 加 1 等于 2。",
    }


def _migrate_database(settings: Settings, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")


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
        if "子问题作答评估器" in prompt:
            content = {
                "results": [
                    {"questionId": "q1", "result": "CORRECT"},
                    {"questionId": "q2", "result": "INCORRECT"},
                ],
                "content": "你已确认第一个条件；第二个问题的答案是 2，请把这些信息补进过程。",
            }
        elif "forceCurrentStepAnswer\": true" in prompt:
            content = {
                "action": "CURRENT_STEP_ANSWER",
                "coveredPoints": [],
                "missingPoints": ["正确计算加法", "得出结果 2"],
                "content": "先把两个 1 合并，再写出这一步得到的结果。",
                "questions": [],
            }
        elif "教学支持生成器" in prompt:
            content = {
                "action": "GUIDED_QUESTIONS",
                "coveredPoints": [],
                "missingPoints": ["正确计算加法", "得出结果 2"],
                "content": "请先回答下面两个问题。",
                "questions": [
                    {"id": "q1", "question": "第一个 1 表示什么？"},
                    {"id": "q2", "question": "两个 1 合起来是多少？"},
                ],
            }
        else:
            content = evaluation
        return AIModelResponse(raw_response="{}", content=json.dumps(content), duration_ms=1)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)


def _start_help(client: TestClient, session: dict[str, object]) -> dict[str, object]:
    selected = client.post(
        f"/api/sessions/{session['id']}/initial-choice",
        json={"choice": "NOT_KNOW", "version": session["version"]},
    )
    assert selected.status_code == 200
    return selected.json()


def test_help_request_sends_guided_questions_and_counts_once(settings, monkeypatch) -> None:
    _stub_ai(monkeypatch, {})
    with _client(settings, monkeypatch) as client:
        session = _start_help(client, _create_session(client))
        response = client.post(
            f"/api/sessions/{session['id']}/request-support",
            json={"mainDraft": "我知道题目有两个 1。", "version": session["version"]},
        )

    assert response.status_code == 200
    saved = response.json()
    assert saved["flowStage"] == "WAIT_GUIDED_ANSWERS"
    assert saved["supportCountRound"] == 1
    assert saved["latestSupport"]["supportKind"] == "GUIDED_QUESTIONS"
    assert len(saved["latestSupport"]["guidedQuestions"]) == 2


def test_guided_answers_are_a_follow_up_not_a_second_support(settings, monkeypatch) -> None:
    _stub_ai(monkeypatch, {})
    with _client(settings, monkeypatch) as client:
        session = _start_help(client, _create_session(client))
        prompted = client.post(
            f"/api/sessions/{session['id']}/request-support",
            json={"mainDraft": "我知道题目有两个 1。", "version": session["version"]},
        ).json()
        response = client.post(
            f"/api/sessions/{session['id']}/guided-answers",
            json={
                "version": prompted["version"],
                "answers": [
                    {"questionId": "q1", "answer": "一个数量"},
                    {"questionId": "q2", "answer": "3"},
                ],
            },
        )

    assert response.status_code == 200
    saved = response.json()
    assert saved["flowStage"] == "WAIT_STUDENT_ACTION"
    assert saved["supportCountRound"] == 1
    assert saved["latestSupport"]["followUpContent"].startswith("你已确认")


def test_third_consecutive_no_progress_request_sends_current_step_answer(
    settings, monkeypatch
) -> None:
    _stub_ai(monkeypatch, {})
    with _client(settings, monkeypatch) as client:
        session = _start_help(client, _create_session(client))
        engine = create_engine(settings.database_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE sessions SET no_progress_help_request_count = 2, "
                        "last_support_draft = :draft WHERE id = :session_id"
                    ),
                    {"draft": "我没有思路。", "session_id": session["id"]},
                )
        finally:
            engine.dispose()
        response = client.post(
            f"/api/sessions/{session['id']}/request-support",
            json={"mainDraft": "我没有思路。", "version": session["version"]},
        )

    assert response.status_code == 200
    saved = response.json()
    assert saved["flowStage"] == "WAIT_STUDENT_ACTION"
    assert saved["latestSupport"]["supportKind"] == "CURRENT_STEP"
    assert saved["supportCountRound"] == 1


def test_support_limit_does_not_create_the_threshold_support_event(settings, monkeypatch) -> None:
    _stub_ai(monkeypatch, {})
    with _client(settings, monkeypatch) as client:
        session = _start_help(client, _create_session(client))
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
        response = client.post(
            f"/api/sessions/{session['id']}/request-support",
            json={"mainDraft": "我没有思路。", "version": session["version"]},
        )

    assert response.status_code == 200
    assert response.json()["flowStage"] == "SHOWING_FULL_SOLUTION"
    assert response.json()["supportCountTotal"] == settings.first_round_support_limit - 1


def test_focused_question_after_explanation_is_counted(settings, monkeypatch) -> None:
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
        response = client.post(
            f"/api/sessions/{session['id']}/text-attempts",
            json={"confirmedText": "我先计算加法。", "version": selected["version"]},
        )

    assert response.status_code == 200
    assert response.json()["supportCountRound"] == 1
    assert response.json()["latestSupport"]["supportType"] == "ASK_FOCUSED_QUESTION"


def test_full_solution_request_is_refused_without_counting_support(settings, monkeypatch) -> None:
    def fake_evaluate(self, prompt: str, schema: dict[str, object]) -> AIModelResponse:
        content = {
            "action": "REFUSE_FULL_SOLUTION",
            "coveredPoints": [],
            "missingPoints": ["正确计算加法", "得出结果 2"],
            "content": "我不能直接给出完整答案，请写出你当前的分析后再继续。",
            "questions": [],
        }
        return AIModelResponse(raw_response="{}", content=json.dumps(content), duration_ms=1)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    with _client(settings, monkeypatch) as client:
        session = _create_session(client)
        selected = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "HAS_QUESTION", "version": session["version"]},
        ).json()
        response = client.post(
            f"/api/sessions/{session['id']}/ask-doubt",
            json={
                "mainDraft": "",
                "doubtText": "请直接给我完整答案。",
                "version": selected["version"],
            },
        )

    assert response.status_code == 200
    saved = response.json()
    assert saved["supportCountRound"] == 0
    assert saved["latestSupport"]["status"] == "REFUSED"
