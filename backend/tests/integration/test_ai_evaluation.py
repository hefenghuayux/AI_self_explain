import json
from pathlib import Path

import pytest
from alembic.config import Config
from conftest import authenticated_test_client
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.schemas.model_request_snapshot import ModelRequestSnapshot
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
            "hasProgress": True,
            "mainReason": "知识应用问题",
            "otherReasons": [],
            "judgeReason": "学生说明了计算方向，但尚未给出结果。",
        }
    )


def focused_teaching_content() -> str:
    return json.dumps(
        {
            "content": "计算过程正确，请补充最后的结果。",
            "questions": [{"id": "teaching-q1", "question": "最后的结果是多少？"}],
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


def test_request_snapshot_migration_upgrade_and_downgrade(settings, monkeypatch) -> None:
    migrate_database(settings, monkeypatch)
    engine = create_engine(settings.database_url)
    try:
        inspector = inspect(engine)
        assert inspector.has_table("ai_evaluations")
        assert inspector.has_table("external_call_records")
        external_call_columns = {
            column["name"] for column in inspector.get_columns("external_call_records")
        }
        assert {
            "transport_status",
            "validation_status",
            "validation_errors",
            "request_snapshot",
        } <= external_call_columns
        assert "status" not in external_call_columns
        evaluation_foreign_keys = inspector.get_foreign_keys("ai_evaluations")
        assert any(
            foreign_key["constrained_columns"] == ["external_call_record_id"]
            and foreign_key["referred_table"] == "external_call_records"
            for foreign_key in evaluation_foreign_keys
        )
    finally:
        engine.dispose()

    alembic_config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.downgrade(alembic_config, "20260810_16")
    engine = create_engine(settings.database_url)
    try:
        inspector = inspect(engine)
        external_call_columns = {
            column["name"] for column in inspector.get_columns("external_call_records")
        }
        assert "status" in external_call_columns
        assert "transport_status" not in external_call_columns
        assert "external_call_record_id" not in {
            column["name"] for column in inspector.get_columns("ai_evaluations")
        }
    finally:
        engine.dispose()


def test_valid_evaluation_and_generated_teaching_are_saved(
    settings, monkeypatch
) -> None:
    def fake_evaluate(self, request: ModelRequestSnapshot) -> AIModelResponse:
        if request.purpose == "AI_TEACHING":
            return AIModelResponse("{\"choices\": []}", focused_teaching_content(), 10)
        prompt = request.transport.messages[4].content
        assert "我先计算 1 加 1。" in prompt
        assert "两个 1 合起来是多少？" in request.transport.messages[1].content
        return AIModelResponse("{\"choices\": []}", valid_evaluation_content(), 12)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    with prepare_client(settings, monkeypatch) as client:
        response = submit_text(client, create_started_session(client))

    assert response.status_code == 200
    saved_session = response.json()
    assert saved_session["status"] == "IN_PROGRESS"
    assert saved_session["flowStage"] == "WAIT_GUIDED_ANSWERS"
    assert saved_session["latestEvaluation"]["correctness"] == "CORRECT"
    assert saved_session["latestSupport"]["guidedQuestions"] == [
        {"id": "teaching-q1", "question": "最后的结果是多少？"}
    ]
    assert saved_session["teachingGeneration"] == {
        "status": "SUCCEEDED",
        "supportEventId": saved_session["latestSupport"]["id"],
    }

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            evaluation = connection.execute(
                text(
                    "SELECT validation_status, validation_errors "
                    "FROM ai_evaluations"
                )
            ).mappings().one()
            call = connection.execute(
                text(
                    "SELECT provider, model, transport_status, validation_status, "
                    "attempt_number, request_snapshot FROM external_call_records "
                    "WHERE call_type = 'AI_EVALUATION'"
                )
            ).mappings().one()
    finally:
        engine.dispose()
    assert evaluation["validation_status"] == "VALID"
    assert json.loads(evaluation["validation_errors"]) == []
    assert dict(call) == {
        "provider": "test-ai",
        "model": "test-ai-model",
        "transport_status": "SUCCESS",
        "validation_status": "VALID",
        "attempt_number": 1,
        "request_snapshot": call["request_snapshot"],
    }
    snapshot = json.loads(call["request_snapshot"])
    assert snapshot["purpose"] == "AI_EVALUATION"
    assert snapshot["transport"]["messages"][0]["content"]


def test_schema_retry_exhaustion_requests_human_review_without_support_count(
    settings, monkeypatch
) -> None:
    # 当前评价契约下仍会出现的非法输出：多返回一个已移除的教学字段。
    invalid_content = json.dumps(
        {
            "correctness": "CORRECT",
            "completeness": "INCOMPLETE",
            "hasProgress": True,
            "mainReason": "知识应用问题",
            "otherReasons": [],
            "judgeReason": "学生说明了计算方向，但尚未给出结果。",
            "feedback": "请补充结果。",
        }
    )

    def fake_evaluate(self, request: ModelRequestSnapshot) -> AIModelResponse:
        return AIModelResponse("{\"choices\": []}", invalid_content, 8)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    with prepare_client(settings, monkeypatch) as client:
        response = submit_text(client, create_started_session(client))

    assert response.status_code == 200
    saved_session = response.json()
    assert saved_session["status"] == "IN_PROGRESS"
    assert saved_session["flowStage"] == "WAIT_STUDENT_ACTION"
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


def test_unknown_evaluation_requests_review_and_keeps_self_explanation_open(
    settings, monkeypatch
) -> None:
    invalid_content = json.dumps(
        {
            "correctness": "UNKNOWN",
            "completeness": "INCOMPLETE",
            "hasProgress": True,
            "mainReason": "知识应用问题",
            "otherReasons": [],
            "judgeReason": "评价值无效。",
        }
    )

    def fake_evaluate(self, request: ModelRequestSnapshot) -> AIModelResponse:
        return AIModelResponse("{\"choices\": []}", invalid_content, 8)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    with prepare_client(settings, monkeypatch) as client:
        response = submit_text(client, create_started_session(client))
        saved_session = response.json()
        continued = client.post(
            f"/api/sessions/{saved_session['id']}/continue",
            json={"version": saved_session["version"]},
        )

    assert response.status_code == 200
    assert saved_session["status"] == "IN_PROGRESS"
    assert saved_session["flowStage"] == "WAIT_STUDENT_ACTION"
    assert saved_session["supportCountRound"] == 0
    assert saved_session["supportCountTotal"] == 0
    assert "AI 结构化评价" in saved_session["needHumanReason"]
    assert saved_session["latestEvaluation"] is None
    assert saved_session["teachingGeneration"] is None
    assert continued.status_code == 200
    assert continued.json()["flowStage"] == "CAPTURING_INPUT"


def test_coordinate_answer_repair_changes_invalid_hint_to_focused_question(
    settings, monkeypatch
) -> None:
    invalid_content = json.dumps(
        {
            "correctness": "CORRECT",
            "completeness": "INCOMPLETE",
            "hasProgress": True,
            "mainReason": "知识应用问题",
            "otherReasons": [],
            "judgeReason": "学生完成了前两问，但尚未把距离关系用于第三问。",
            "nextAction": "GIVE_HINT",
        }
    )
    corrected_content = json.dumps(
        {
            "correctness": "CORRECT",
            "completeness": "INCOMPLETE",
            "hasProgress": True,
            "mainReason": "知识应用问题",
            "otherReasons": [],
            "judgeReason": "学生完成了前两问，但尚未把距离关系用于第三问。",
        }
    )
    requests: list[ModelRequestSnapshot] = []

    def fake_evaluate(self, request: ModelRequestSnapshot) -> AIModelResponse:
        requests.append(request)
        if request.purpose == "AI_TEACHING":
            content = json.dumps(
                {
                    "content": "请再检查点 P 到原点的距离表示。",
                    "questions": [
                        {"id": "teaching-q1", "question": "点 P 到原点的距离如何表示？"}
                    ],
                }
            )
        else:
            evaluation_requests = [item for item in requests if item.purpose == "AI_EVALUATION"]
            content = invalid_content if len(evaluation_requests) == 1 else corrected_content
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
    assert saved_session["flowStage"] == "WAIT_GUIDED_ANSWERS"
    evaluation_requests = [item for item in requests if item.purpose == "AI_EVALUATION"]
    assert len(evaluation_requests) == 2
    assert (
        "Extra inputs are not permitted" in evaluation_requests[1].transport.messages[4].content
    )
    assert evaluation_requests[1].blocks.retry_context["validationErrors"]

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            evaluations = connection.execute(
                text(
                    "SELECT validation_status FROM ai_evaluations ORDER BY id"
                )
            ).mappings().all()
    finally:
        engine.dispose()
    assert [dict(evaluation) for evaluation in evaluations] == [
        {"validation_status": "INVALID"},
        {"validation_status": "VALID"},
    ]


def test_complete_evaluation_sets_completion_with_deterministic_label(
    settings, monkeypatch
) -> None:
    completed_content = json.dumps(
        {
            "correctness": "CORRECT",
            "completeness": "COMPLETE",
            "hasProgress": True,
            "mainReason": None,
            "otherReasons": [],
            "judgeReason": None,
        }
    )

    def fake_evaluate(self, request: ModelRequestSnapshot) -> AIModelResponse:
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
    assert saved_session["teachingGeneration"] == {"status": "NOT_REQUIRED"}


def test_transport_retry_exhaustion_requests_review_and_allows_another_explanation(
    settings, monkeypatch
) -> None:
    calls = 0

    def fake_evaluate(self, request: ModelRequestSnapshot) -> AIModelResponse:
        nonlocal calls
        if request.purpose == "AI_TEACHING":
            return AIModelResponse("{\"choices\": []}", focused_teaching_content(), 9)
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
        continued = client.post(
            f"/api/sessions/{first_session['id']}/continue",
            json={"version": first_session["version"]},
        )
        retry_response = client.post(
            f"/api/sessions/{first_session['id']}/text-attempts",
            json={
                "confirmedText": "我重新说明，1 加 1 等于 2。",
                "version": continued.json()["version"],
            },
        )

    assert first_response.status_code == 200
    assert first_session["status"] == "IN_PROGRESS"
    assert first_session["flowStage"] == "WAIT_STUDENT_ACTION"
    assert "AI 评价服务" in first_session["needHumanReason"]
    assert continued.status_code == 200
    assert continued.json()["flowStage"] == "CAPTURING_INPUT"
    assert retry_response.status_code == 200
    assert retry_response.json()["flowStage"] == "WAIT_GUIDED_ANSWERS"

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            attempt_count = connection.execute(
                text("SELECT COUNT(*) FROM explanation_attempts")
            ).scalar_one()
            error_count = connection.execute(
                text(
                    "SELECT COUNT(*) FROM external_call_records "
                    "WHERE transport_status = 'ERROR'"
                )
            ).scalar_one()
    finally:
        engine.dispose()
    assert attempt_count == 2
    assert error_count == settings.ai_transport_max_retries + 1


@pytest.mark.parametrize("failure_kind", ["transport", "validation"])
def test_teaching_failure_keeps_evaluation_without_support_side_effects(
    settings, monkeypatch, failure_kind: str
) -> None:
    def fake_evaluate(self, request: ModelRequestSnapshot) -> AIModelResponse:
        if request.purpose == "AI_EVALUATION":
            return AIModelResponse("{\"choices\": []}", valid_evaluation_content(), 8)
        if failure_kind == "transport":
            raise AITransportError(
                error_type="AI_SERVICE_ERROR",
                message="供应商教学服务不可用",
                duration_ms=5,
            )
        return AIModelResponse(
            "{\"choices\": []}",
            '{"content":"无效教学输出","questions":[],"action":"COMPLETE"}',
            8,
        )

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    with prepare_client(settings, monkeypatch) as client:
        started = create_started_session(client)
        response = submit_text(client, started)
        current = client.get(f"/api/sessions/{started['id']}")

    assert response.status_code == 200
    assert response.json()["needHumanReason"] == "教学生成失败，会话已进入人工处理"
    assert "供应商" not in response.text
    assert current.status_code == 200
    assert current.json()["status"] == "IN_PROGRESS"
    assert current.json()["flowStage"] == "WAIT_STUDENT_ACTION"
    assert current.json()["supportCountRound"] == 0
    assert current.json()["supportCountTotal"] == 0
    assert current.json()["latestEvaluation"]["correctness"] == "CORRECT"
    assert current.json()["latestSupport"] is None
    assert current.json()["teachingGeneration"] is None

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM ai_evaluations")).scalar_one() == 1
            assert connection.execute(text("SELECT COUNT(*) FROM support_events")).scalar_one() == 0
            failure_event = connection.execute(
                text(
                    "SELECT related_evaluation_id, related_support_event_id "
                    "FROM state_transition_events "
                    "WHERE trigger_type = 'AI_TEACHING_RETRY_EXHAUSTED'"
                )
            ).mappings().one()
    finally:
        engine.dispose()
    assert failure_event["related_evaluation_id"] is not None
    assert failure_event["related_support_event_id"] is None
