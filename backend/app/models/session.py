from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True, nullable=False)
    initial_choice: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    flow_stage: Mapped[str] = mapped_column(String(40), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    support_count_round: Mapped[int] = mapped_column(Integer, nullable=False)
    support_count_total: Mapped[int] = mapped_column(Integer, nullable=False)
    no_progress_count: Mapped[int] = mapped_column(Integer, nullable=False)
    solution_exposed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    completion_type: Mapped[str | None] = mapped_column(String(30))
    need_human_reason: Mapped[str | None] = mapped_column(Text)
    covered_points_current_round: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    covered_points_all: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    paused_from_stage: Mapped[str | None] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
