import json
from pathlib import Path

from alembic.config import Config
from conftest import authenticated_test_client
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.services.ai_evaluation import AIModelClient, AIModelResponse, AITransportError


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


def coordinate_question_payload() -> dict[str, object]:
    return {
        "questionContent": "在平面直角坐标系中，直线 y = -2x + 6 与坐标轴交于 A、B。",
        "standardAnswer": "A(3, 0)、B(0, 6)、三角形 AOB 面积为 9，P 坐标为 (2, 0) 或 (-2, 0)。",
        "rubricPoints": [
            "令 y = 0 求得 x = 3，并写出 A(3, 0)。",
            "令 x = 0 求得 y = 6，并写出 B(0, 6)。",
            "利用直角三角形面积公式计算出 S三角形AOB = 9。",
            "用 OP = |t| 建立 3|t| = 6 的面积方程。",
            "得到 P(2, 0) 和 P(-2, 0) 两个坐标。",
        ],
        "commonErrors": ["遗漏 P 在 x 轴上时 OP = |t|"],
        "alternativeSolutions": ["先由面积公式得到 |t| = 2"],
        "layeredHints": ["先确定 POB 的底和高"],
        "guidedQuestions": ["面积公式中底和高分别是什么？"],
        "fullSolution": "由 OP = |t| 和 1/2 × OP × OB = 6 求 P 坐标。",
    }


def valid_evaluation_content() -> str:
    return json.dumps(
        {
            "correctness": "CORRECT",
            "completeness": "INCOMPLETE",
            "coveredPoints": ["正确计算加法"],
            "missingPoints": ["得出结果 2"],
            "errorEvidence": [],
            "feedback": "计算过程正确，请补充最后的结果。",
            "confidence": 1,
            "nextAction": "ASK_FOCUSED_QUESTION",
            "needHumanReason": None,
        }
    )


def migrate_database(settings, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    alembic_config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.upgrade(alembic_config, "head")


def prepare_client(settings, monkeypatch) -> TestClient:
    migrate_database(settings, monkeypatch)
    return authenticated_test_client(settings)


def create_started_session(
    client: TestClient, question: dict[str, object] | None = None
) -> dict[str, object]:
    question_response = client.post("/api/questions", json=question or question_payload())
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


def submit_text(client: TestClient, session: dict[str, object]) -> TestClient:
    return client.post(
        f"/api/sessions/{session['id']}/text-attempts",
        json={"confirmedText": "我先计算 1 加 1。", "version": session["version"]},
    )


def test_migration_creates_ai_evaluation_tables(settings, monkeypatch) -> None:
    migrate_database(settings, monkeypatch)
    engine = create_engine(settings.database_url)
    try:
        inspector = inspect(engine)
        assert inspector.has_table("ai_evaluations")
        assert inspector.has_table("external_call_records")
    finally:
        engine.dispose()


def test_valid_evaluation_is_saved_with_call_record_and_feedback(
    settings, monkeypatch
) -> None:
    def fake_evaluate(self, prompt: str, schema: dict[str, object]) -> AIModelResponse:
        assert "正确计算加法" in schema["properties"]["coveredPoints"]["items"]["enum"]
        assert "我先计算 1 加 1。" in prompt
        assert "两个 1 合起来是多少？" in prompt
        return AIModelResponse("{\"choices\": []}", valid_evaluation_content(), 12)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    with prepare_client(settings, monkeypatch) as client:
        response = submit_text(client, create_started_session(client))

    assert response.status_code == 200
    saved_session = response.json()
    assert saved_session["status"] == "IN_PROGRESS"
    assert saved_session["flowStage"] == "WAIT_STUDENT_ACTION"
    assert saved_session["latestEvaluation"]["feedback"] == "计算过程正确，请补充最后的结果。"

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            evaluation = connection.execute(
                text(
                    "SELECT validation_status, covered_points, validation_errors "
                    "FROM ai_evaluations"
                )
            ).mappings().one()
            call = connection.execute(
                text("SELECT provider, model, status, attempt_number FROM external_call_records")
            ).mappings().one()
    finally:
        engine.dispose()
    assert evaluation["validation_status"] == "VALID"
    assert json.loads(evaluation["covered_points"]) == ["正确计算加法"]
    assert json.loads(evaluation["validation_errors"]) == []
    assert dict(call) == {
        "provider": "test-ai",
        "model": "test-ai-model",
        "status": "SUCCESS",
        "attempt_number": 1,
    }


def test_schema_retry_exhaustion_enters_need_human_without_support_count(
    settings, monkeypatch
) -> None:
    invalid_content = json.dumps(
        {
            "correctness": "CORRECT",
            "completeness": "INCOMPLETE",
            "coveredPoints": ["正确计算加法"],
            "missingPoints": ["得出结果 2"],
            "errorEvidence": [],
            "feedback": "请补充结果。",
            "confidence": 1,
            "nextAction": "GIVE_HINT",
            "needHumanReason": None,
        }
    )

    def fake_evaluate(self, prompt: str, schema: dict[str, object]) -> AIModelResponse:
        return AIModelResponse("{\"choices\": []}", invalid_content, 8)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    with prepare_client(settings, monkeypatch) as client:
        response = submit_text(client, create_started_session(client))

    assert response.status_code == 200
    saved_session = response.json()
    assert saved_session["status"] == "NEED_HUMAN"
    assert saved_session["supportCountRound"] == 0
    assert saved_session["supportCountTotal"] == 0
    assert "AI 结构化评价" in saved_session["needHumanReason"]

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            invalid_count = connection.execute(
                text("SELECT COUNT(*) FROM ai_evaluations WHERE validation_status = 'INVALID'")
            ).scalar_one()
    finally:
        engine.dispose()
    assert invalid_count == settings.ai_schema_max_retries + 1


def test_coordinate_answer_repair_changes_invalid_hint_to_focused_question(
    settings, monkeypatch
) -> None:
    invalid_content = json.dumps(
        {
            "correctness": "CORRECT",
            "completeness": "INCOMPLETE",
            "coveredPoints": [
                "令 y = 0 求得 x = 3，并写出 A(3, 0)。",
                "令 x = 0 求得 y = 6，并写出 B(0, 6)。",
                "利用直角三角形面积公式计算出 S三角形AOB = 9。",
            ],
            "missingPoints": [
                "用 OP = |t| 建立 3|t| = 6 的面积方程。",
                "得到 P(2, 0) 和 P(-2, 0) 两个坐标。",
            ],
            "errorEvidence": [],
            "feedback": "第三问可使用 OP = |t| 列面积方程。",
            "confidence": 1,
            "nextAction": "GIVE_HINT",
            "needHumanReason": None,
        }
    )
    corrected_content = json.dumps(
        {
            "correctness": "CORRECT",
            "completeness": "INCOMPLETE",
            "coveredPoints": [
                "令 y = 0 求得 x = 3，并写出 A(3, 0)。",
                "令 x = 0 求得 y = 6，并写出 B(0, 6)。",
                "利用直角三角形面积公式计算出 S三角形AOB = 9。",
            ],
            "missingPoints": [
                "用 OP = |t| 建立 3|t| = 6 的面积方程。",
                "得到 P(2, 0) 和 P(-2, 0) 两个坐标。",
            ],
            "errorEvidence": [],
            "feedback": "第三问中，点 P 在 x 轴上时，P 到原点的距离应如何表示？",
            "confidence": 1,
            "nextAction": "ASK_FOCUSED_QUESTION",
            "needHumanReason": None,
        }
    )
    prompts: list[str] = []

    def fake_evaluate(self, prompt: str, schema: dict[str, object]) -> AIModelResponse:
        prompts.append(prompt)
        content = invalid_content if len(prompts) == 1 else corrected_content
        return AIModelResponse("{\"choices\": []}", content, 8)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    with prepare_client(settings, monkeypatch) as client:
        started_session = create_started_session(client, coordinate_question_payload())
        response = client.post(
            f"/api/sessions/{started_session['id']}/text-attempts",
            json={
                "confirmedText": (
                    "第一问，令x=0，则y=6，得B（0,6），令y=0，则x=3，得A（3,0）。"
                    "第二问，三角形AOB面积=AO*BO/2=9。第三问不太会。"
                ),
                "version": started_session["version"],
            },
        )

    assert response.status_code == 200
    saved_session = response.json()
    assert saved_session["status"] == "IN_PROGRESS"
    assert saved_session["flowStage"] == "WAIT_STUDENT_ACTION"
    assert saved_session["latestEvaluation"]["nextAction"] == "ASK_FOCUSED_QUESTION"
    assert len(prompts) == 2
    assert "CORRECT | INCOMPLETE | ASK_FOCUSED_QUESTION" in prompts[1]
    assert "不能作为本次确认文本的直接评价动作" in prompts[1]

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            evaluations = connection.execute(
                text(
                    "SELECT validation_status, next_action FROM ai_evaluations "
                    "ORDER BY id"
                )
            ).mappings().all()
    finally:
        engine.dispose()
    assert [dict(evaluation) for evaluation in evaluations] == [
        {"validation_status": "INVALID", "next_action": "GIVE_HINT"},
        {"validation_status": "VALID", "next_action": "ASK_FOCUSED_QUESTION"},
    ]


def test_complete_evaluation_sets_completion_with_deterministic_label(
    settings, monkeypatch
) -> None:
    completed_content = json.dumps(
        {
            "correctness": "CORRECT",
            "completeness": "COMPLETE",
            "coveredPoints": ["正确计算加法", "得出结果 2"],
            "missingPoints": [],
            "errorEvidence": [],
            "feedback": "你的讲解正确且完整。",
            "confidence": 1,
            "nextAction": "COMPLETE",
            "needHumanReason": None,
        }
    )

    def fake_evaluate(self, prompt: str, schema: dict[str, object]) -> AIModelResponse:
        return AIModelResponse("{\"choices\": []}", completed_content, 8)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    with prepare_client(settings, monkeypatch) as client:
        response = submit_text(client, create_started_session(client))

    assert response.status_code == 200
    saved_session = response.json()
    assert saved_session["status"] == "COMPLETED"
    assert saved_session["completionType"] == "INDEPENDENT"
    assert saved_session["supportCountRound"] == 0
    assert saved_session["supportCountTotal"] == 0


def test_transport_retry_exhaustion_keeps_confirmed_text_for_retry(
    settings, monkeypatch
) -> None:
    calls = 0

    def fake_evaluate(self, prompt: str, schema: dict[str, object]) -> AIModelResponse:
        nonlocal calls
        calls += 1
        if calls <= settings.ai_transport_max_retries + 1:
            raise AITransportError(
                error_type="AI_SERVICE_ERROR",
                message="测试模型服务不可用",
                duration_ms=5,
            )
        return AIModelResponse("{\"choices\": []}", valid_evaluation_content(), 9)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    monkeypatch.setattr("app.services.ai_evaluation.time.sleep", lambda _: None)
    with prepare_client(settings, monkeypatch) as client:
        first_response = submit_text(client, create_started_session(client))
        first_session = first_response.json()
        retry_response = client.post(
            f"/api/sessions/{first_session['id']}/evaluate",
            json={"version": first_session["version"]},
        )

    assert first_response.status_code == 200
    assert first_session["status"] == "IN_PROGRESS"
    assert first_session["flowStage"] == "CONFIRMING_TEXT"
    assert retry_response.status_code == 200
    assert retry_response.json()["flowStage"] == "WAIT_STUDENT_ACTION"

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            attempt_count = connection.execute(
                text("SELECT COUNT(*) FROM explanation_attempts")
            ).scalar_one()
            error_count = connection.execute(
                text("SELECT COUNT(*) FROM external_call_records WHERE status = 'ERROR'")
            ).scalar_one()
    finally:
        engine.dispose()
    assert attempt_count == 1
    assert error_count == settings.ai_transport_max_retries + 1
