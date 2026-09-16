from datetime import datetime

from sqlalchemy import JSON, DateTime, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Question(Base):
    __tablename__ = "self_explain_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    tiku_question_id: Mapped[int | None] = mapped_column(unique=True)
    question_content: Mapped[str] = mapped_column(Text(length=16_777_215), nullable=False)
    standard_answer: Mapped[str | None] = mapped_column(Text(length=16_777_215))
    rubric_points: Mapped[list[str] | None] = mapped_column(JSON)
    common_errors: Mapped[list[str] | None] = mapped_column(JSON)
    alternative_solutions: Mapped[list[str] | None] = mapped_column(JSON)
    layered_hints: Mapped[list[str] | None] = mapped_column(JSON)
    guided_questions: Mapped[list[str] | None] = mapped_column(JSON)
    full_solution: Mapped[str | None] = mapped_column(Text(length=16_777_215))
    grade_period: Mapped[int | None] = mapped_column(SmallInteger)
    subject: Mapped[str | None] = mapped_column(String(20))
    q_type: Mapped[int | None] = mapped_column(SmallInteger)
    difficulty_level: Mapped[int | None] = mapped_column(SmallInteger)
    review: Mapped[str | None] = mapped_column(String(2048))
    topics: Mapped[str | None] = mapped_column(Text(length=16_777_215))
    method: Mapped[str | None] = mapped_column(Text(length=16_777_215))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def evaluation_mode(self) -> str:
        if self.rubric_points:
            return "FULL_RUBRIC"
        if self.standard_answer is None and self.full_solution is None:
            return "AI_GENERAL"
        return "BASIC"

    @property
    def rubric_point_count(self) -> int:
        return len(self.rubric_points or [])
