import json
from pathlib import Path

from alembic.config import Config
from conftest import authenticated_test_client
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from alembic import command
from app.core.config import Settings
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
    return authenticated_test_client(settings)


def _create_session(client: TestClient) -> dict[str, object]:
    question = client.post("/api/questions", json=_question_payload())
    assert question.status_code == 201
    response = client.post("/api/sessions", json={"questionId": question.json()["id"]})
    assert response.status_code == 201
    return response.json()


def _stub_ai(monkeypatch, evaluation: dict[str, object]) -> None:
    def fake_evaluate(self, request) -> AIModelResponse:
        prompt = request.transport.messages[0].content
        if request.purpose == "AI_EVALUATION":
            terminal = (
                evaluation["correctness"] == "CORRECT"
                and evaluation["completeness"] == "COMPLETE"
            )
            content = {
                "correctness": evaluation["correctness"],
                "completeness": evaluation["completeness"],
                "hasProgress": evaluation.get("hasProgress", True),
                "mainReason": None if terminal else "知识应用问题",
                "otherReasons": [],
                "judgeReason": None if terminal else "学生尚未完成当前推理。",
            }
        elif "instructionFromRules" in request.blocks.session_context:
            action = request.blocks.session_context["instructionFromRules"]["allowedAction"]
            content = {
                "content": evaluation["feedback"],
                "questions": (
                    evaluation["guidedQuestions"]
                    if action == "ASK_FOCUSED_QUESTION"
                    else []
                ),
            }
        elif "子问题作答评估器" in prompt:
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
                "missingPoints": ["正确计算加法", "得出结果 2"],
                "content": "先把两个 1 合并，再写出这一步得到的结果。",
                "questions": [],
            }
        elif "教学支持生成器" in prompt:
            content = {
                "action": "GUIDED_QUESTIONS",
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


def test_help_request_generates_questions_without_configured_guided_questions(
    settings, monkeypatch
) -> None:
    _stub_ai(monkeypatch, {})
    with _client(settings, monkeypatch) as client:
        payload = {**_question_payload(), "guidedQuestions": []}
        question = client.post("/api/questions", json=payload)
        assert question.status_code == 201
        created_session = client.post(
            "/api/sessions", json={"questionId": question.json()["id"]}
        )
        assert created_session.status_code == 201
        session = _start_help(client, created_session.json())

        response = client.post(
            f"/api/sessions/{session['id']}/request-support",
            json={"mainDraft": "我知道题目有两个 1。", "version": session["version"]},
        )

    assert response.status_code == 200
    saved = response.json()
    assert saved["flowStage"] == "WAIT_GUIDED_ANSWERS"
    assert saved["supportCountRound"] == 1
    assert len(saved["latestSupport"]["guidedQuestions"]) == 2


def test_guided_answers_can_be_submitted_separately_without_second_support(
    settings, monkeypatch
) -> None:
    _stub_ai(monkeypatch, {})
    with _client(settings, monkeypatch) as client:
        session = _start_help(client, _create_session(client))
        prompted = client.post(
            f"/api/sessions/{session['id']}/request-support",
            json={"mainDraft": "我知道题目有两个 1。", "version": session["version"]},
        ).json()
        first_response = client.post(
            f"/api/sessions/{session['id']}/guided-answers",
            json={
                "version": prompted["version"],
                "answers": [{"questionId": "q1", "answer": "一个数量"}],
            },
        )
        assert first_response.status_code == 200
        partially_answered = first_response.json()
        assert partially_answered["flowStage"] == "WAIT_GUIDED_ANSWERS"
        assert partially_answered["supportCountRound"] == 1
        assert partially_answered["latestSupport"]["guidedAnswers"] == [
            {"questionId": "q1", "answer": "一个数量"}
        ]
        assert partially_answered["latestSupport"]["followUpContent"] is None

        response = client.post(
            f"/api/sessions/{session['id']}/guided-answers",
            json={
                "version": partially_answered["version"],
                "answers": [{"questionId": "q2", "answer": "3"}],
            },
        )

    assert response.status_code == 200
    saved = response.json()
    assert saved["flowStage"] == "WAIT_STUDENT_ACTION"
    assert saved["supportCountRound"] == 1
    assert saved["latestSupport"]["guidedAnswers"] == [
        {"questionId": "q1", "answer": "一个数量"},
        {"questionId": "q2", "answer": "3"},
    ]
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


def test_not_understanding_first_solution_requests_review_and_allows_continuing(
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
                        "UPDATE sessions SET support_count_round = :support_count "
                        "WHERE id = :session_id"
                    ),
                    {
                        "support_count": settings.first_round_support_limit - 1,
                        "session_id": session["id"],
                    },
                )
        finally:
            engine.dispose()
        solution_response = client.post(
            f"/api/sessions/{session['id']}/request-support",
            json={"mainDraft": "我没有思路。", "version": session["version"]},
        )
        assert solution_response.status_code == 200
        not_understood = client.post(
            f"/api/sessions/{session['id']}/full-solution-understanding",
            json={"understood": False, "version": solution_response.json()["version"]},
        )
        continued = client.post(
            f"/api/sessions/{session['id']}/continue",
            json={"version": not_understood.json()["version"]},
        )

    assert not_understood.status_code == 200
    assert not_understood.json()["status"] == "IN_PROGRESS"
    assert not_understood.json()["flowStage"] == "WAIT_STUDENT_ACTION"
    assert not_understood.json()["needHumanReason"] == "学生在第一轮完整解析后仍表示不会"
    assert continued.status_code == 200
    assert continued.json()["flowStage"] == "CAPTURING_INPUT"


def test_focused_question_after_explanation_is_a_non_counting_guided_question(
    settings, monkeypatch
) -> None:
    evaluation = {
        "correctness": "CORRECT",
        "completeness": "INCOMPLETE",
        "missingPoints": ["得出结果 2"],
        "feedback": "请补充结果。",
        "confidence": 1,
        "nextAction": "ASK_FOCUSED_QUESTION",
        "needHumanReason": None,
        "guidedQuestions": [{"id": "evaluation-q1", "question": "结果是多少？"}],
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
    assert response.json()["flowStage"] == "WAIT_GUIDED_ANSWERS"
    assert response.json()["supportCountRound"] == 0
    assert response.json()["latestSupport"]["supportType"] == "ASK_FOCUSED_QUESTION"
    assert response.json()["latestSupport"]["guidedQuestions"] == [
        {"id": "evaluation-q1", "question": "结果是多少？"}
    ]


def test_wrong_incomplete_answer_creates_counted_correction_without_question(
    settings, monkeypatch
) -> None:
    evaluation = {
        "correctness": "WRONG",
        "completeness": "INCOMPLETE",
        "missingPoints": ["正确计算加法", "得出结果 2"],
        "feedback": "你把 1 加 1 算成了 3，请重新检查。",
        "confidence": 1,
        "nextAction": "CORRECT_AND_ASK",
        "needHumanReason": None,
        "guidedQuestions": [
            {"id": "evaluation-q1", "question": "两个 1 合起来实际是多少？"}
        ],
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
            json={"confirmedText": "1 加 1 等于 3", "version": selected["version"]},
        )

    assert response.status_code == 200
    saved = response.json()
    assert saved["flowStage"] == "WAIT_STUDENT_ACTION"
    assert saved["supportCountRound"] == 1
    assert saved["latestSupport"]["supportType"] == "GIVE_CORRECTION"
    assert saved["latestSupport"]["guidedQuestions"] is None


def test_doubt_and_appeal_are_allowed_while_evaluation_questions_are_pending(
    settings, monkeypatch
) -> None:
    evaluation = {
        "correctness": "WRONG",
        "completeness": "INCOMPLETE",
        "missingPoints": ["正确计算加法", "得出结果 2"],
        "feedback": "请重新检查。",
        "confidence": 1,
        "nextAction": "CORRECT_AND_ASK",
        "needHumanReason": None,
        "guidedQuestions": [{"id": "evaluation-q1", "question": "两个 1 合起来实际是多少？"}],
    }
    _stub_ai(monkeypatch, evaluation)
    with _client(settings, monkeypatch) as client:
        session = _create_session(client)
        selected = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "KNOW", "version": session["version"]},
        ).json()
        pending_questions = client.post(
            f"/api/sessions/{session['id']}/text-attempts",
            json={"confirmedText": "1 加 1 等于 3", "version": selected["version"]},
        ).json()
        doubt = client.post(
            f"/api/sessions/{session['id']}/ask-doubt",
            json={
                "mainDraft": "1 加 1 等于 3",
                "doubtText": "为什么这里需要重新计算？",
                "version": pending_questions["version"],
            },
        )

        another_session = _create_session(client)
        another_selected = client.post(
            f"/api/sessions/{another_session['id']}/initial-choice",
            json={"choice": "KNOW", "version": another_session["version"]},
        ).json()
        another_pending_questions = client.post(
            f"/api/sessions/{another_session['id']}/text-attempts",
            json={"confirmedText": "1 加 1 等于 3", "version": another_selected["version"]},
        ).json()
        appeal = client.post(
            f"/api/sessions/{another_session['id']}/appeal",
            json={
                "reason": "我认为 1 加 1 等于 3 的判断没有问题。",
                "version": another_pending_questions["version"],
            },
        )

    assert doubt.status_code == 200
    assert doubt.json()["supportCountRound"] == 2
    assert appeal.status_code == 200
    assert appeal.json()["status"] == "IN_PROGRESS"
    assert appeal.json()["flowStage"] == "WAIT_STUDENT_ACTION"
    assert appeal.json()["supportCountRound"] == 1
    assert appeal.json()["needHumanReason"].startswith("学生申诉：")


def test_appeal_is_allowed_while_help_questions_are_pending_without_evaluation(
    settings, monkeypatch
) -> None:
    _stub_ai(monkeypatch, {})
    with _client(settings, monkeypatch) as client:
        session = _start_help(client, _create_session(client))
        pending_questions = client.post(
            f"/api/sessions/{session['id']}/request-support",
            json={"mainDraft": "我不知道怎样判断最小值。", "version": session["version"]},
        ).json()
        appeal = client.post(
            f"/api/sessions/{session['id']}/appeal",
            json={
                "reason": "这个提示没有回答我的疑问。",
                "version": pending_questions["version"],
            },
        )

    assert appeal.status_code == 200
    assert appeal.json()["status"] == "IN_PROGRESS"
    assert appeal.json()["flowStage"] == "WAIT_STUDENT_ACTION"
    assert appeal.json()["supportCountRound"] == 1
    assert appeal.json()["needHumanReason"].startswith("学生申诉：")


def test_full_solution_request_is_refused_without_counting_support(settings, monkeypatch) -> None:
    def fake_evaluate(self, request) -> AIModelResponse:
        content = {
            "action": "REFUSE_FULL_SOLUTION",
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
