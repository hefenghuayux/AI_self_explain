"""add guided support state

Revision ID: 20260721_06
Revises: 20260721_05
Create Date: 2026-07-21 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260721_06"
down_revision: str | None = "20260721_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("no_progress_help_request_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("sessions", sa.Column("current_draft", sa.Text(), nullable=False, server_default=""))
    op.add_column("sessions", sa.Column("last_support_draft", sa.Text(), nullable=False, server_default=""))
    op.add_column(
        "support_events",
        sa.Column("support_kind", sa.String(length=40), nullable=False, server_default="EVALUATION"),
    )
    op.add_column("support_events", sa.Column("main_draft", sa.Text(), nullable=True))
    op.add_column("support_events", sa.Column("doubt_text", sa.Text(), nullable=True))
    op.add_column("support_events", sa.Column("guided_questions", sa.JSON(), nullable=True))
    op.add_column("support_events", sa.Column("guided_answers", sa.JSON(), nullable=True))
    op.add_column("support_events", sa.Column("follow_up_content", sa.Text(), nullable=True))


def downgrade() -> None:
    for column in (
        "follow_up_content",
        "guided_answers",
        "guided_questions",
        "doubt_text",
        "main_draft",
        "support_kind",
    ):
        op.drop_column("support_events", column)
    for column in ("last_support_draft", "current_draft", "no_progress_help_request_count"):
        op.drop_column("sessions", column)
