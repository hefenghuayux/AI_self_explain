"""persist cancellable AI runs

Revision ID: 20261014_33
Revises: 20261014_32
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_33"
down_revision: str | None = "20261014_32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("active_run_id", sa.String(64), nullable=True))
    op.create_index("ix_sessions_active_run_id", "sessions", ["active_run_id"])
    op.add_column(
        "state_transition_events", sa.Column("cancelled_run_id", sa.String(64), nullable=True)
    )
    op.create_index(
        "ix_state_transition_events_cancelled_run_id",
        "state_transition_events", ["cancelled_run_id"],
    )
    op.create_table(
        "ai_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("checkpoints", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ai_runs_session_id", "ai_runs", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_runs_session_id", table_name="ai_runs")
    op.drop_table("ai_runs")
    op.drop_index("ix_state_transition_events_cancelled_run_id", table_name="state_transition_events")
    op.drop_column("state_transition_events", "cancelled_run_id")
    op.drop_index("ix_sessions_active_run_id", table_name="sessions")
    op.drop_column("sessions", "active_run_id")
