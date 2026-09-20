from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MasteryCheck(Base):
    """一次对话后掌握度核验：问题、学生回答、回答评价与最终结论。"""

    __tablename__ = "mastery_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id"), index=True, nullable=False
    )
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("explanation_attempts.id"), index=True, nullable=False
    )
    evaluation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_evaluations.id"), index=True, nullable=False
    )
    questions: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    answers: Mapped[list[dict[str, object]] | None] = mapped_column(JSON)
    results: Mapped[list[dict[str, object]] | None] = mapped_column(JSON)
    outcome: Mapped[str | None] = mapped_column(String(20))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def is_completed(self) -> bool:
        return self.outcome is not None
