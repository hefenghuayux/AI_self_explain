"""add realtime asr audio files

Revision ID: 20260721_08
Revises: 20260721_07
Create Date: 2026-07-21 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260721_08"
down_revision: str | None = "20260721_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audio_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audio_files_session_id", "audio_files", ["session_id"])
    with op.batch_alter_table("explanation_attempts") as batch_op:
        batch_op.alter_column("confirmed_text", existing_type=sa.Text(), nullable=True)
        batch_op.alter_column(
            "confirmed_at", existing_type=sa.DateTime(timezone=True), nullable=True
        )
        batch_op.create_foreign_key(
            "fk_explanation_attempts_audio_file_id",
            "audio_files",
            ["audio_file_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("explanation_attempts") as batch_op:
        batch_op.drop_constraint("fk_explanation_attempts_audio_file_id", type_="foreignkey")
        batch_op.alter_column("confirmed_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch_op.alter_column("confirmed_text", existing_type=sa.Text(), nullable=False)
    op.drop_index("ix_audio_files_session_id", table_name="audio_files")
    op.drop_table("audio_files")
