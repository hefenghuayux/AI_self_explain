from datetime import datetime

from sqlalchemy import JSON, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_content: Mapped[str] = mapped_column(Text, nullable=False)
    standard_answer: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_points: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    common_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    alternative_solutions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    layered_hints: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    guided_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    full_solution: Mapped[str] = mapped_column(Text, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
