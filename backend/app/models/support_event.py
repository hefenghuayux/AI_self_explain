from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SupportEvent(Base):
    __tablename__ = "support_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True, nullable=False)
    evaluation_id: Mapped[int | None] = mapped_column(ForeignKey("ai_evaluations.id"), index=True)
    support_type: Mapped[str] = mapped_column(String(40), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    support_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="EVALUATION")
    main_draft: Mapped[str | None] = mapped_column(Text)
    doubt_text: Mapped[str | None] = mapped_column(Text)
    guided_questions: Mapped[list[dict[str, str]] | None] = mapped_column(JSON)
    guided_answers: Mapped[list[dict[str, str]] | None] = mapped_column(JSON)
    follow_up_content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
