from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from alembic import command
from app.core.config import Settings
from app.main import create_app


def question_payload() -> dict[str, object]:
    return {
        "questionContent": "计算 1 + 1。",
        "standardAnswer": "2",
        "rubricPoints": ["正确计算加法", "得出结果 2"],
        "commonErrors": ["把结果写成 3"],
        "alternativeSolutions": ["使用实物计数"],
        "layeredHints": ["先数一数两个数", "再合并两组数量"],
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
    with TestClient(create_app(migrated_settings)) as test_client:
        yield test_client


def test_migration_creates_questions_table(migrated_settings: Settings) -> None:
    engine = create_engine(migrated_settings.database_url)
    try:
        assert inspect(engine).has_table("questions")
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
    assert created["createdAt"]
    assert created["updatedAt"]

    list_response = question_client.get("/api/questions")
    detail_response = question_client.get(f"/api/questions/{created['id']}")

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [created["id"]]
    assert detail_response.status_code == 200
    assert detail_response.json() == created


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("standardAnswer", " "),
        ("rubricPoints", ["有效评分点", " "]),
        ("rubricPoints", ["有效评分点", "有效评分点"]),
        ("layeredHints", [" "]),
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
    assert updated["fullSolution"] == original_payload["fullSolution"]
