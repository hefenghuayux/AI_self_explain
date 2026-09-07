from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AIEvaluation(Base):
    __tablename__ = "ai_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True, nullable=False)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("explanation_attempts.id"), index=True, nullable=False
    )
    external_call_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("external_call_records.id"), index=True
    )
    correctness: Mapped[str | None] = mapped_column(String(20))
    completeness: Mapped[str | None] = mapped_column(String(20))
    covered_points: Mapped[list[str] | None] = mapped_column(JSON)
    error_evidence: Mapped[list[dict[str, str]] | None] = mapped_column(JSON)
    need_human_reason: Mapped[str | None] = mapped_column(Text)
    evaluation_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="FULL_RUBRIC")
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_response: Mapped[str | None] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(String(30), nullable=False)
    validation_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    request_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
