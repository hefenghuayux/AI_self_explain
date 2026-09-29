from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExplanationStep(Base):
    __tablename__ = "explanation_steps"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'SAVED', 'SUBMITTED')",
            name="ck_explanation_steps_status",
        ),
        CheckConstraint("seq > 0", name="ck_explanation_steps_seq_positive"),
        UniqueConstraint(
            "session_id",
            "draft_id",
            "seq",
            name="uq_explanation_steps_session_draft_seq",
        ),
        Index(
            "ix_explanation_steps_session_round_draft",
            "session_id",
            "round",
            "draft_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True, nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_id: Mapped[str] = mapped_column(String(36), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    step_content: Mapped[str | None] = mapped_column(Text)
    explain_transcript: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
