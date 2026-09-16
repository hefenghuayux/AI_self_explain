"""create support events

Revision ID: 20260721_05
Revises: 20260720_04
Create Date: 2026-07-21 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260721_05"
down_revision: str | None = "20260720_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "support_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("evaluation_id", sa.Integer(), nullable=True),
        sa.Column("support_type", sa.String(length=40), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["evaluation_id"], ["ai_evaluations.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_support_events_evaluation_id", "support_events", ["evaluation_id"])
    op.create_index("ix_support_events_session_id", "support_events", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_support_events_session_id", table_name="support_events")
    op.drop_index("ix_support_events_evaluation_id", table_name="support_events")
    op.drop_table("support_events")
