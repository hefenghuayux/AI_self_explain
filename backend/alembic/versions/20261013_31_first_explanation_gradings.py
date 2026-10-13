"""add independent first explanation grading records

Revision ID: 20261013_31
Revises: 20261013_30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261013_31"
down_revision: str | None = "20261013_30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "first_explanation_gradings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("evaluation_status", sa.String(length=20), nullable=False),
        sa.Column("correctness_score", sa.Integer(), nullable=True),
        sa.Column("completeness_score", sa.Integer(), nullable=True),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("evaluation_error", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("standard_version", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["attempt_id"], ["explanation_attempts.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", name="uq_first_explanation_gradings_attempt"),
    )
    op.create_index(
        "ix_first_explanation_gradings_session_id", "first_explanation_gradings", ["session_id"]
    )
    op.create_index(
        "ix_first_explanation_gradings_attempt_id", "first_explanation_gradings", ["attempt_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_first_explanation_gradings_attempt_id", table_name="first_explanation_gradings"
    )
    op.drop_index(
        "ix_first_explanation_gradings_session_id", table_name="first_explanation_gradings"
    )
    op.drop_table("first_explanation_gradings")
