"""add ai evaluation records

Revision ID: 20260720_04
Revises: 20260720_03
Create Date: 2026-07-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260720_04"
down_revision: str | None = "20260720_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_evaluations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("correctness", sa.String(length=20), nullable=True),
        sa.Column("completeness", sa.String(length=20), nullable=True),
        sa.Column("covered_points", sa.JSON(), nullable=True),
        sa.Column("missing_points", sa.JSON(), nullable=True),
        sa.Column("error_evidence", sa.JSON(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("next_action", sa.String(length=40), nullable=True),
        sa.Column("need_human_reason", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("model_provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("validation_status", sa.String(length=30), nullable=False),
        sa.Column("validation_errors", sa.JSON(), nullable=False),
        sa.Column("request_duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["attempt_id"], ["explanation_attempts.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_evaluations_attempt_id", "ai_evaluations", ["attempt_id"])
    op.create_index("ix_ai_evaluations_session_id", "ai_evaluations", ["session_id"])
    op.create_table(
        "external_call_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("call_type", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_call_records_session_id", "external_call_records", ["session_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_external_call_records_session_id", table_name="external_call_records")
    op.drop_table("external_call_records")
    op.drop_index("ix_ai_evaluations_session_id", table_name="ai_evaluations")
    op.drop_index("ix_ai_evaluations_attempt_id", table_name="ai_evaluations")
    op.drop_table("ai_evaluations")
