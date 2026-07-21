import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_ENV = {
    "FIRST_ROUND_SUPPORT_LIMIT": "6",
    "SECOND_ROUND_SUPPORT_LIMIT": "3",
    "NO_PROGRESS_LIMIT": "2",
    "GUIDED_QUESTION_REQUEST_LIMIT": "2",
    "AI_REQUEST_TIMEOUT_SECONDS": "60",
    "AI_TRANSPORT_MAX_RETRIES": "2",
    "AI_SCHEMA_MAX_RETRIES": "1",
    "AI_RETRY_BACKOFF_SECONDS": "1,2",
    "ASR_REQUEST_TIMEOUT_SECONDS": "60",
    "ASR_TRANSPORT_MAX_RETRIES": "2",
    "ASR_RETRY_BACKOFF_SECONDS": "1,2",
    "AUDIO_MAX_SIZE_MIB": "20",
    "AUDIO_MAX_DURATION_SECONDS": "300",
    "DATABASE_BUSY_TIMEOUT_SECONDS": "5",
    "LOG_MAX_SIZE_MIB": "10",
    "LOG_BACKUP_COUNT": "5",
    "AI_PROVIDER": "test-ai",
    "AI_BASE_URL": "https://ai.test/v1",
    "AI_API_KEY": "test-ai-secret",
    "AI_MODEL": "test-ai-model",
    "ASR_PROVIDER": "test-asr",
    "ASR_BASE_URL": "https://asr.test/v1",
    "ASR_API_KEY": "test-asr-secret",
    "ASR_MODEL": "test-asr-model",
    "PROMPT_VERSION": "test-v1",
    "DATABASE_URL": "sqlite:///:memory:",
    "AUDIO_STORAGE_DIR": "test-audio",
    "LOG_DIR": "test-logs",
}

for key, value in TEST_ENV.items():
    os.environ[key] = value

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def settings_values(tmp_path: Path) -> dict[str, str]:
    return {
        **{key.lower(): value for key, value in TEST_ENV.items()},
        "database_url": f"sqlite:///{tmp_path / 'test.db'}",
        "audio_storage_dir": str(tmp_path / "audio"),
        "log_dir": str(tmp_path / "logs"),
    }


@pytest.fixture
def settings(settings_values: dict[str, str]) -> Settings:
    return Settings(**settings_values)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
