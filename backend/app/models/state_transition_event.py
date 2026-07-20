from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StateTransitionEvent(Base):
    __tablename__ = "state_transition_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str] = mapped_column(String(30), nullable=False)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    from_flow_stage: Mapped[str | None] = mapped_column(String(40))
    to_flow_stage: Mapped[str] = mapped_column(String(40), nullable=False)
    before_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    after_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    related_attempt_id: Mapped[int | None] = mapped_column(Integer)
    related_evaluation_id: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
