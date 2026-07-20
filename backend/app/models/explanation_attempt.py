from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExplanationAttempt(Base):
    __tablename__ = "explanation_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True, nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    input_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    audio_file_id: Mapped[int | None] = mapped_column(Integer)
    asr_transcript: Mapped[str | None] = mapped_column(Text)
    confirmed_text: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
