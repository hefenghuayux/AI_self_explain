from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_accepts_confirmed_configuration(settings_values: dict[str, str]) -> None:
    settings = Settings(**settings_values)

    assert settings.first_round_support_limit == 6
    assert settings.ai_retry_backoff_seconds == (1.0, 2.0)
    assert settings.ai_api_key.get_secret_value() == "test-ai-secret"


@pytest.mark.parametrize(
    "field",
    [
        "first_round_support_limit",
        "ai_provider",
        "database_url",
        "audio_storage_dir",
    ],
)
def test_rejects_missing_required_configuration(
    settings_values: dict[str, str], field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_values.pop(field)
    monkeypatch.delenv(field.upper())

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **settings_values)

    assert field.lower() in str(error.value).lower()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("first_round_support_limit", "0"),
        ("no_progress_limit", "-1"),
        ("ai_request_timeout_seconds", "0"),
        ("ai_transport_max_retries", "-1"),
        ("audio_max_size_mib", "0"),
        ("log_backup_count", "0"),
    ],
)
def test_rejects_invalid_positive_and_count_values(
    settings_values: dict[str, str], field: str, value: str
) -> None:
    settings_values[field] = value

    with pytest.raises(ValidationError):
        Settings(**settings_values)


def test_rejects_backoff_length_mismatch(settings_values: dict[str, str]) -> None:
    settings_values["ai_retry_backoff_seconds"] = "1"

    with pytest.raises(ValidationError, match="AI_RETRY_BACKOFF_SECONDS"):
        Settings(**settings_values)


def test_rejects_non_positive_backoff(settings_values: dict[str, str]) -> None:
    settings_values["asr_retry_backoff_seconds"] = "1,0"

    with pytest.raises(ValidationError):
        Settings(**settings_values)


def test_rejects_non_sqlite_database(settings_values: dict[str, str]) -> None:
    settings_values["database_url"] = "postgresql://localhost/test"

    with pytest.raises(ValidationError, match="SQLite"):
        Settings(**settings_values)


def test_rejects_file_where_directory_is_required(
    settings_values: dict[str, str], tmp_path: Path
) -> None:
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("content", encoding="utf-8")
    settings_values["audio_storage_dir"] = str(file_path)

    with pytest.raises(ValidationError, match="路径不是目录"):
        Settings(**settings_values)


def test_rejects_blank_directory_path(settings_values: dict[str, str]) -> None:
    settings_values["log_dir"] = " "

    with pytest.raises(ValidationError, match="目录路径不能为空"):
        Settings(**settings_values)
