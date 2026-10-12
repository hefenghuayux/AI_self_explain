"""对话后核验的 API 级集成测试：规则触发、状态转换与前端契约。"""

import json
from pathlib import Path

from alembic.config import Config
from conftest import authenticated_test_client
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from alembic import command
from app.core.config import Settings
from app.services.ai_evaluation import AIModelClient, AIModelResponse

MASTERY_QUESTION_ID = "mc1"


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


def _client(settings: Settings, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")
    return authenticated_test_client(settings)


def _create_session(client: TestClient) -> dict[str, object]:
    question = client.post("/api/questions", json=_question_payload())
    assert question.status_code == 201
    response = client.post("/api/sessions", json={"questionId": question.json()["id"]})
    assert response.status_code == 201
    return response.json()


def _choose(client: TestClient, session: dict[str, object], choice: str) -> dict[str, object]:
    response = client.post(
        f"/api/sessions/{session['id']}/initial-choice",
        json={"choice": choice, "version": session["version"]},
    )
    assert response.status_code == 200
    return response.json()


def _set_support_counts(settings: Settings, session_id: object, count: int, exposed: bool) -> None:
    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE sessions SET support_count_round = :count, "
                    "support_count_total = :count, solution_exposed = :exposed "
                    "WHERE id = :session_id"
                ),
                {"count": count, "exposed": exposed, "session_id": session_id},
            )
    finally:
        engine.dispose()


def _events_of_type(
    settings: Settings, session_id: object, event_type: str
) -> list[dict[str, object]]:
    """按 seq 读取一个会话里某类会话事件。"""
    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT run_id, data FROM session_events "
                        "WHERE session_id = :session_id AND event_type = :event_type "
                        "ORDER BY seq"
                    ),
                    {"session_id": session_id, "event_type": event_type},
                )
                .mappings()
                .all()
            )
    finally:
        engine.dispose()
    return [{"run_id": row["run_id"], "data": json.loads(row["data"])} for row in rows]


def _stub_ai(monkeypatch, *, passed: bool = True) -> None:
    """按 purpose 返回确定性输出。

    第一次自讲评价为“错误但不完整”，用于提供非终态评价证据；第二次为
    “正确且完整”，触发第一轮结束。核验与核验评价返回固定结构。
    """
    evaluations = [("WRONG", "INCOMPLETE"), ("CORRECT", "COMPLETE")]

    def fake_evaluate(self, request) -> AIModelResponse:
        if request.purpose == "AI_EVALUATION":
            correctness, completeness = evaluations.pop(0)
            terminal = correctness == "CORRECT" and completeness == "COMPLETE"
            content = {
                "correctness": correctness,
                "completeness": completeness,
                "hasProgress": True,
                "mainReason": None if terminal else "知识应用问题",
                "otherReasons": [],
                "judgeReason": None if terminal else "学生尚未说明计算依据。",
            }
        elif request.purpose == "AI_TEACHING":
            content = {"content": "请补充合并两个数量的依据。", "questions": []}
        elif request.purpose == "AI_MASTERY_CHECK":
            content = {
                "questions": [
                    {
                        "id": MASTERY_QUESTION_ID,
                        "question": "你在合并两个数量时依据的是什么？",
                        "evidenceRefs": [
                            {
                                "source": "EVALUATION",
                                "sourceId": "1",
                                "quote": "学生尚未说明计算依据。",
                            }
                        ],
                    }
                ]
            }
        elif request.purpose == "MASTERY_CHECK_ASSESSMENT":
            content = {
                "results": [
                    {
                        "questionId": MASTERY_QUESTION_ID,
                        "passed": passed,
                        "basis": "学生说明了合并数量的依据。",
                    }
                ]
            }
        else:
            raise AssertionError(f"未预期的模型调用：{request.purpose}")
        return AIModelResponse(raw_response="{}", content=json.dumps(content), duration_ms=1)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)


def _reach_mastery_check(
    client: TestClient,
    settings: Settings,
    monkeypatch,
    *,
    support_count: int = 1,
    solution_exposed: bool = False,
) -> dict[str, object]:
    """走到第一轮结束：先留下一条非终态评价，再以正确且完整结束第一轮。"""
    _stub_ai(monkeypatch)
    session = _choose(client, _create_session(client), "KNOW")
    first = client.post(
        f"/api/sessions/{session['id']}/text-attempts",
        json={"confirmedText": "我把两个 1 合起来。", "version": session["version"]},
    )
    assert first.status_code == 200
    continued = client.post(
        f"/api/sessions/{session['id']}/continue",
        json={"version": first.json()["version"]},
    )
    assert continued.status_code == 200
    _set_support_counts(settings, session["id"], support_count, solution_exposed)
    response = client.post(
        f"/api/sessions/{session['id']}/text-attempts",
        json={"confirmedText": "1 加 1 等于 2。", "version": continued.json()["version"]},
    )
    assert response.status_code == 200
    return response.json()


def test_supported_first_round_end_enters_mastery_check(settings, monkeypatch) -> None:
    with _client(settings, monkeypatch) as client:
        saved = _reach_mastery_check(client, settings, monkeypatch)

    assert saved["needHumanReason"] is None
    assert saved["status"] == "IN_PROGRESS"
    assert saved["flowStage"] == "WAIT_MASTERY_CHECK"
    assert saved["completionType"] is None
    # 新流程不再开启第二轮，轮次与支持计数都保持不变。
    assert saved["round"] == 1
    assert saved["supportCountRound"] == 1
    assert [item["id"] for item in saved["masteryCheck"]["questions"]] == [MASTERY_QUESTION_ID]
    assert saved["masteryCheck"]["answers"] is None
    assert saved["masteryCheck"]["outcome"] is None


def test_all_passed_mastery_check_completes_the_session(settings, monkeypatch) -> None:
    with _client(settings, monkeypatch) as client:
        prompted = _reach_mastery_check(client, settings, monkeypatch)
        response = client.post(
            f"/api/sessions/{prompted['id']}/mastery-check-answers",
            json={
                "version": prompted["version"],
                "answers": [
                    {"questionId": MASTERY_QUESTION_ID, "answer": "依据是把两个 1 合起来。"}
                ],
            },
        )
        timeline = client.get(f"/api/sessions/{prompted['id']}/timeline").json()

    assert response.status_code == 200
    saved = response.json()
    assert saved["status"] == "COMPLETED"
    assert saved["flowStage"] == "WAIT_STUDENT_ACTION"
    assert saved["completionType"] == "AFTER_MASTERY_CHECK"
    assert saved["masteryCheck"]["outcome"] == "COMPLETED"
    assert saved["masteryCheck"]["results"][0]["passed"] is True
    assert saved["supportCountRound"] == 1
    assert [item["eventType"] for item in timeline[-3:]] == [
        "MASTERY_QUESTIONS",
        "SUBMISSION",
        "MASTERY_RESULT",
    ]
    assert timeline[-2]["submissionType"] == "MASTERY_ANSWER"


def test_mastery_answers_write_user_message_event(settings, monkeypatch) -> None:
    """核验回答也要写 user.message，并与回答评价共用一次运行。

    事件文本与对话页显示的同一次提交保持一致，避免两处各写一份格式。
    """
    with _client(settings, monkeypatch) as client:
        prompted = _reach_mastery_check(client, settings, monkeypatch)
        response = client.post(
            f"/api/sessions/{prompted['id']}/mastery-check-answers",
            json={
                "version": prompted["version"],
                "answers": [
                    {"questionId": MASTERY_QUESTION_ID, "answer": "依据是把两个 1 合起来。"}
                ],
            },
        )
        assert response.status_code == 200
        timeline = client.get(f"/api/sessions/{prompted['id']}/timeline").json()
        messages = _events_of_type(settings, prompted["id"], "user.message")
        requests = _events_of_type(settings, prompted["id"], "model.requested")

    submitted = next(
        item for item in timeline if item.get("submissionType") == "MASTERY_ANSWER"
    )
    assert messages[-1]["data"]["text"] == submitted["content"]
    assert "依据是把两个 1 合起来。" in messages[-1]["data"]["text"]
    assert messages[-1]["data"]["inputType"] == "text"
    assert messages[-1]["run_id"] == (
        f"run_session_{prompted['id']}_mastery_check_"
        f"MASTERY_CHECK_ASSESSMENT_{prompted['version']}"
    )
    assert requests[-1]["run_id"] == messages[-1]["run_id"]


def test_failed_mastery_check_ends_as_needs_review(settings, monkeypatch) -> None:
    with _client(settings, monkeypatch) as client:
        prompted = _reach_mastery_check(client, settings, monkeypatch)
        _stub_ai(monkeypatch, passed=False)
        response = client.post(
            f"/api/sessions/{prompted['id']}/mastery-check-answers",
            json={
                "version": prompted["version"],
                "answers": [
                    {"questionId": MASTERY_QUESTION_ID, "answer": "我不确定。"}
                ],
            },
        )

    assert response.status_code == 200
    saved = response.json()
    assert saved["status"] == "NEEDS_REVIEW"
    assert saved["completionType"] == "AFTER_MASTERY_CHECK"
    assert saved["masteryCheck"]["outcome"] == "NEEDS_REVIEW"
    assert saved["masteryCheck"]["results"][0]["passed"] is False
    # 非成功终态仍然结束本题，但不进入第二轮。
    assert saved["round"] == 1


def test_low_support_first_round_end_completes_without_mastery_check(
    settings, monkeypatch
) -> None:
    with _client(settings, monkeypatch) as client:
        saved = _reach_mastery_check(client, settings, monkeypatch, support_count=0)

    assert saved["status"] == "COMPLETED"
    assert saved["completionType"] == "INDEPENDENT"
    assert saved["masteryCheck"] is None


def test_one_support_without_solution_enters_mastery_check(settings, monkeypatch) -> None:
    with _client(settings, monkeypatch) as client:
        saved = _reach_mastery_check(client, settings, monkeypatch, support_count=1)

    assert saved["status"] == "IN_PROGRESS"
    assert saved["flowStage"] == "WAIT_MASTERY_CHECK"
    assert saved["masteryCheck"] is not None


def test_solution_exposed_with_one_support_enters_mastery_check(settings, monkeypatch) -> None:
    with _client(settings, monkeypatch) as client:
        saved = _reach_mastery_check(
            client, settings, monkeypatch, support_count=1, solution_exposed=True
        )

    assert saved["flowStage"] == "WAIT_MASTERY_CHECK"
    assert saved["masteryCheck"] is not None


def test_mastery_check_answers_must_match_sent_questions(settings, monkeypatch) -> None:
    with _client(settings, monkeypatch) as client:
        prompted = _reach_mastery_check(client, settings, monkeypatch)
        response = client.post(
            f"/api/sessions/{prompted['id']}/mastery-check-answers",
            json={
                "version": prompted["version"],
                "answers": [{"questionId": "unknown", "answer": "随便答一句。"}],
            },
        )

    assert response.status_code == 409
    assert "一一对应" in response.json()["detail"]


def test_mastery_check_answers_are_rejected_after_completion(settings, monkeypatch) -> None:
    with _client(settings, monkeypatch) as client:
        prompted = _reach_mastery_check(client, settings, monkeypatch)
        payload = {
            "answers": [{"questionId": MASTERY_QUESTION_ID, "answer": "依据是合并两个 1。"}]
        }
        first = client.post(
            f"/api/sessions/{prompted['id']}/mastery-check-answers",
            json={"version": prompted["version"], **payload},
        )
        second = client.post(
            f"/api/sessions/{prompted['id']}/mastery-check-answers",
            json={"version": first.json()["version"], **payload},
        )

    assert first.status_code == 200
    assert second.status_code == 409


def test_missing_evaluation_evidence_requests_human_review(settings, monkeypatch) -> None:
    """学生只请求支持、从未自讲时没有评价证据，核验不生成，转人工复核。"""
    _stub_ai(monkeypatch)
    with _client(settings, monkeypatch) as client:
        session = _choose(client, _create_session(client), "NOT_KNOW")
        _set_support_counts(
            settings, session["id"], settings.first_round_support_limit, False
        )
        solution = client.post(
            f"/api/sessions/{session['id']}/request-support",
            json={"mainDraft": "我没有思路。", "version": session["version"]},
        )
        assert solution.json()["flowStage"] == "SHOWING_FULL_SOLUTION"
        response = client.post(
            f"/api/sessions/{session['id']}/full-solution-understanding",
            json={"understood": True, "version": solution.json()["version"]},
        )

    assert response.status_code == 200
    saved = response.json()
    assert saved["status"] == "IN_PROGRESS"
    assert saved["flowStage"] == "WAIT_STUDENT_ACTION"
    assert saved["needHumanReason"] == "缺少可用于核验的评价证据，已转人工复核"
    assert saved["masteryCheck"] is None
