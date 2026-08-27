from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from conftest import authenticated_test_client
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, inspect

from alembic import command
from app.core.config import Settings
from app.models.question import Question


def question_payload() -> dict[str, object]:
    return {
        "questionContent": "计算 1 + 1。",
        "standardAnswer": "2",
        "rubricPoints": ["正确计算加法", "得出结果 2"],
        "commonErrors": ["把结果写成 3"],
        "alternativeSolutions": ["使用实物计数"],
        "layeredHints": ["先数一数两个数", "再合并两组数量"],
        "guidedQuestions": ["两个 1 分别表示什么？", "合并后应如何表示结果？"],
        "fullSolution": "1 加 1 等于 2。",
    }


@pytest.fixture
def migrated_settings(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    alembic_config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.upgrade(alembic_config, "head")
    return settings


@pytest.fixture
def question_client(migrated_settings: Settings) -> Iterator[TestClient]:
    with authenticated_test_client(migrated_settings) as test_client:
        yield test_client


def test_migration_creates_self_explain_questions_table(migrated_settings: Settings) -> None:
    engine = create_engine(migrated_settings.database_url)
    try:
        assert inspect(engine).has_table("self_explain_questions")
        columns = inspect(engine).get_columns("self_explain_questions")
        assert "archived_at" in {column["name"] for column in columns}
        assert "tiku_question_id" in {column["name"] for column in columns}
    finally:
        engine.dispose()


def test_question_can_be_saved_and_read_completely(question_client: TestClient) -> None:
    payload = question_payload()

    create_response = question_client.post("/api/questions", json=payload)

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["id"] > 0
    assert created["rubricPoints"] == payload["rubricPoints"]
    assert created["layeredHints"] == payload["layeredHints"]
    assert created["guidedQuestions"] == payload["guidedQuestions"]
    assert created["createdAt"]
    assert created["updatedAt"]

    list_response = question_client.get("/api/questions")
    detail_response = question_client.get(f"/api/questions/{created['id']}")

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["items"]] == [created["id"]]
    assert "standardAnswer" not in list_response.json()["items"][0]
    assert detail_response.status_code == 200
    assert detail_response.json() == created


def test_question_can_be_created_and_updated_without_ai_material(
    question_client: TestClient,
) -> None:
    payload = {"questionContent": "可补录题目"}

    create_response = question_client.post("/api/questions", json=payload)

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["evaluationMode"] == "AI_GENERAL"
    assert created["rubricPoints"] is None

    update_response = question_client.put(
        f"/api/questions/{created['id']}",
        json={**payload, "questionContent": "更新后的题目", "rubricPoints": ["补录评分点"]},
    )

    assert update_response.status_code == 200
    assert update_response.json()["evaluationMode"] == "FULL_RUBRIC"
    assert update_response.json()["rubricPoints"] == ["补录评分点"]


def test_migrated_question_with_empty_guided_questions_can_be_read(
    question_client: TestClient, migrated_settings: Settings
) -> None:
    engine = create_engine(migrated_settings.database_url)
    try:
        with engine.begin() as connection:
            result = connection.execute(
                insert(Question).values(
                    question_content="历史题目",
                    standard_answer="历史答案",
                    rubric_points=["历史评分点"],
                    common_errors=["历史常见错误"],
                    alternative_solutions=["历史其他解法"],
                    layered_hints=["历史提示"],
                    full_solution="历史完整解析",
                )
            )
            question_id = result.inserted_primary_key[0]
    finally:
        engine.dispose()

    list_response = question_client.get("/api/questions")
    detail_response = question_client.get(f"/api/questions/{question_id}")

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["rubricPointCount"] == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["guidedQuestions"] == []


def test_question_list_prioritizes_rubric_and_returns_evaluation_mode(
    question_client: TestClient,
) -> None:
    without_rubric = question_client.post("/api/questions", json={"questionContent": "无评分点"})
    with_rubric = question_client.post(
        "/api/questions",
        json={"questionContent": "有评分点", "rubricPoints": ["评分点"]},
    )

    response = question_client.get("/api/questions")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [
        with_rubric.json()["id"],
        without_rubric.json()["id"],
    ]
    assert [item["evaluationMode"] for item in response.json()["items"]] == [
        "FULL_RUBRIC",
        "AI_GENERAL",
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rubricPoints", ["有效评分点", " "]),
        ("rubricPoints", ["有效评分点", "有效评分点"]),
        ("layeredHints", [" "]),
        ("guidedQuestions", [" "]),
        ("guidedQuestions", ["提示问题", "提示问题"]),
    ],
)
def test_question_api_rejects_invalid_material(
    question_client: TestClient, field: str, value: object
) -> None:
    payload = question_payload()
    payload[field] = value

    response = question_client.post("/api/questions", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"]


def test_question_update_preserves_unedited_material(question_client: TestClient) -> None:
    original_payload = question_payload()
    created = question_client.post("/api/questions", json=original_payload).json()
    updated_payload = {**original_payload, "questionContent": "计算 2 + 2。"}

    update_response = question_client.put(f"/api/questions/{created['id']}", json=updated_payload)

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["questionContent"] == "计算 2 + 2。"
    assert updated["standardAnswer"] == original_payload["standardAnswer"]
    assert updated["rubricPoints"] == original_payload["rubricPoints"]
    assert updated["commonErrors"] == original_payload["commonErrors"]
    assert updated["alternativeSolutions"] == original_payload["alternativeSolutions"]
    assert updated["layeredHints"] == original_payload["layeredHints"]
    assert updated["guidedQuestions"] == original_payload["guidedQuestions"]
    assert updated["fullSolution"] == original_payload["fullSolution"]


def test_question_can_be_archived_and_restored(question_client: TestClient) -> None:
    original_payload = question_payload()
    created = question_client.post("/api/questions", json=original_payload).json()

    archive_response = question_client.post(f"/api/questions/{created['id']}/archive")

    assert archive_response.status_code == 200
    assert archive_response.json()["archivedAt"]
    assert question_client.get("/api/questions").json()["items"] == []
    archived_list = question_client.get("/api/questions?include_archived=true")
    assert [item["id"] for item in archived_list.json()["items"]] == [created["id"]]
    assert question_client.get(f"/api/questions/{created['id']}").status_code == 200

    edit_response = question_client.put(f"/api/questions/{created['id']}", json=original_payload)
    assert edit_response.status_code == 409
    assert edit_response.json()["detail"] == "已归档题目不能编辑"

    restore_response = question_client.post(f"/api/questions/{created['id']}/restore")

    assert restore_response.status_code == 200
    assert restore_response.json()["archivedAt"] is None
    assert [item["id"] for item in question_client.get("/api/questions").json()["items"]] == [
        created["id"]
    ]


def test_question_list_filters_paginates_and_returns_dynamic_options(
    question_client: TestClient, migrated_settings: Settings
) -> None:
    engine = create_engine(migrated_settings.database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(Question),
                [
                    {
                        "question_content": "学段二语文题干 100%",
                        "grade_period": 2,
                        "subject": "Y",
                    },
                    {
                        "question_content": "学段二数学题干",
                        "grade_period": 2,
                        "subject": "S",
                    },
                    {
                        "question_content": "学段三语文题干",
                        "grade_period": 3,
                        "subject": "Y",
                    },
                ],
            )
    finally:
        engine.dispose()

    response = question_client.get(
        "/api/questions",
        params={
            "page": 1,
            "page_size": 1,
            "grade_period": 2,
            "subject": "Y",
            "keyword": "100%",
        },
    )
    options_response = question_client.get("/api/questions/filter-options")

    assert response.status_code == 200
    assert response.json()["pagination"] == {
        "page": 1,
        "pageSize": 1,
        "total": 1,
        "totalPages": 1,
    }
    assert response.json()["items"][0]["questionContent"] == "学段二语文题干 100%"
    assert options_response.status_code == 200
    assert options_response.json() == {"gradePeriods": [2, 3], "subjects": ["S", "Y"]}
