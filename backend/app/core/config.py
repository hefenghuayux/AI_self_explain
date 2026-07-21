from pathlib import Path
from typing import Annotated, Self

from pydantic import (
    AnyHttpUrl,
    Field,
    PositiveFloat,
    PositiveInt,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
BackoffSequence = Annotated[tuple[PositiveFloat, ...], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    first_round_support_limit: PositiveInt
    second_round_support_limit: PositiveInt
    no_progress_limit: PositiveInt
    guided_question_request_limit: PositiveInt

    ai_request_timeout_seconds: PositiveFloat
    ai_transport_max_retries: Annotated[int, Field(ge=0)]
    ai_schema_max_retries: Annotated[int, Field(ge=0)]
    ai_retry_backoff_seconds: BackoffSequence

    asr_request_timeout_seconds: PositiveFloat
    asr_transport_max_retries: Annotated[int, Field(ge=0)]
    asr_retry_backoff_seconds: BackoffSequence

    audio_max_size_mib: PositiveInt
    audio_max_duration_seconds: PositiveInt
    database_busy_timeout_seconds: PositiveFloat
    log_max_size_mib: PositiveInt
    log_backup_count: PositiveInt

    ai_provider: NonEmptyString
    ai_base_url: AnyHttpUrl
    ai_api_key: SecretStr
    ai_model: NonEmptyString

    asr_provider: NonEmptyString
    asr_base_url: AnyHttpUrl
    asr_api_key: SecretStr
    asr_model: NonEmptyString

    prompt_version: NonEmptyString
    database_url: NonEmptyString
    audio_storage_dir: Path
    log_dir: Path

    @field_validator("ai_retry_backoff_seconds", "asr_retry_backoff_seconds", mode="before")
    @classmethod
    def parse_backoff_sequence(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        if not value.strip():
            raise ValueError("退避间隔不能为空")
        try:
            return tuple(float(item.strip()) for item in value.split(","))
        except ValueError as error:
            raise ValueError("退避间隔必须是逗号分隔的正数") from error

    @field_validator("ai_api_key", "asr_api_key")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("API 密钥不能为空")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith(("sqlite:///", "sqlite+pysqlite:///")):
            raise ValueError("DATABASE_URL 必须使用 SQLite URL")
        return value

    @field_validator("audio_storage_dir", "log_dir", mode="before")
    @classmethod
    def validate_directory_value(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("目录路径不能为空")
        return value

    @field_validator("audio_storage_dir", "log_dir")
    @classmethod
    def validate_directory_path(cls, value: Path) -> Path:
        if value.exists() and not value.is_dir():
            raise ValueError(f"路径不是目录：{value}")
        return value

    @model_validator(mode="after")
    def validate_retry_backoffs(self) -> Self:
        if len(self.ai_retry_backoff_seconds) != self.ai_transport_max_retries:
            raise ValueError("AI_RETRY_BACKOFF_SECONDS 数量必须等于 AI_TRANSPORT_MAX_RETRIES")
        if len(self.asr_retry_backoff_seconds) != self.asr_transport_max_retries:
            raise ValueError("ASR_RETRY_BACKOFF_SECONDS 数量必须等于 ASR_TRANSPORT_MAX_RETRIES")
        return self
