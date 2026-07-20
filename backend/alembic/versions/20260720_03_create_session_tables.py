"""create session tables

Revision ID: 20260720_03
Revises: 20260720_02
Create Date: 2026-07-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260720_03"
down_revision: str | None = "20260720_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("initial_choice", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("flow_stage", sa.String(length=40), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("support_count_round", sa.Integer(), nullable=False),
        sa.Column("support_count_total", sa.Integer(), nullable=False),
        sa.Column("no_progress_count", sa.Integer(), nullable=False),
        sa.Column("solution_exposed", sa.Boolean(), nullable=False),
        sa.Column("completion_type", sa.String(length=30), nullable=True),
        sa.Column("need_human_reason", sa.Text(), nullable=True),
        sa.Column("covered_points_current_round", sa.JSON(), nullable=False),
        sa.Column("covered_points_all", sa.JSON(), nullable=False),
        sa.Column("paused_from_stage", sa.String(length=40), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_question_id", "sessions", ["question_id"])
    op.create_table(
        "explanation_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("input_mode", sa.String(length=20), nullable=False),
        sa.Column("audio_file_id", sa.Integer(), nullable=True),
        sa.Column("asr_transcript", sa.Text(), nullable=True),
        sa.Column("confirmed_text", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_explanation_attempts_session_id", "explanation_attempts", ["session_id"])
    op.create_table(
        "state_transition_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("trigger_type", sa.String(length=40), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=False),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("from_flow_stage", sa.String(length=40), nullable=True),
        sa.Column("to_flow_stage", sa.String(length=40), nullable=False),
        sa.Column("before_snapshot", sa.JSON(), nullable=False),
        sa.Column("after_snapshot", sa.JSON(), nullable=False),
        sa.Column("related_attempt_id", sa.Integer(), nullable=True),
        sa.Column("related_evaluation_id", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_state_transition_events_session_id", "state_transition_events", ["session_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_state_transition_events_session_id", table_name="state_transition_events")
    op.drop_table("state_transition_events")
    op.drop_index("ix_explanation_attempts_session_id", table_name="explanation_attempts")
    op.drop_table("explanation_attempts")
    op.drop_index("ix_sessions_question_id", table_name="sessions")
    op.drop_table("sessions")
