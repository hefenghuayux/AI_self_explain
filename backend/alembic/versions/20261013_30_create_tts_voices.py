"""create TTS voice catalog and user speech preferences

Revision ID: 20261013_30
Revises: 20261012_29
Create Date: 2026-10-13 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261013_30"
down_revision: str | None = "20261012_29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tts_voices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("voice_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=150), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(length=50), nullable=True),
        sa.Column("teacher", sa.String(length=100), nullable=True),
        sa.Column("variant", sa.String(length=10), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column("source_start_seconds", sa.Float(), nullable=True),
        sa.Column("source_end_seconds", sa.Float(), nullable=True),
        sa.Column("source_evidence", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("voice_id"),
    )
    op.create_table(
        "user_tts_preferences",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("voice_id", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["voice_id"], ["tts_voices.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_tts_preferences")
    op.drop_table("tts_voices")
