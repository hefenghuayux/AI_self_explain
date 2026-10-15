from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class TTSVoice(Base):
    __tablename__ = "tts_voices"

    id: Mapped[int] = mapped_column(primary_key=True)
    education_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    voice_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # 数据库记录创建或导入时间，不代表上游音色创建时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    runtime_config: Mapped["TTSVoiceRuntimeConfig"] = relationship(
        back_populates="voice", uselist=False, cascade="all, delete-orphan"
    )


class TTSVoiceRuntimeConfig(Base):
    __tablename__ = "tts_voice_runtime_configs"

    tts_voice_id: Mapped[int] = mapped_column(
        ForeignKey("tts_voices.id", ondelete="CASCADE"), primary_key=True
    )
    voice_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    source_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_start_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_end_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    voice: Mapped[TTSVoice] = relationship(back_populates="runtime_config")


class TTSSpeechSettings(Base):
    __tablename__ = "user_tts_preferences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    voice_id: Mapped[int | None] = mapped_column(ForeignKey("tts_voices.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
