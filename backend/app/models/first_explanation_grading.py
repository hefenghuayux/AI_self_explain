from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FirstExplanationGrading(Base):
    __tablename__ = "first_explanation_gradings"
    __table_args__ = (UniqueConstraint("attempt_id", name="uq_first_explanation_gradings_attempt"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True, nullable=False)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("explanation_attempts.id"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    evaluation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    correctness_score: Mapped[int | None] = mapped_column(Integer)
    completeness_score: Mapped[int | None] = mapped_column(Integer)
    total_score: Mapped[float | None] = mapped_column()
    report: Mapped[dict[str, object] | None] = mapped_column(JSON)
    evaluation_error: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    standard_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
