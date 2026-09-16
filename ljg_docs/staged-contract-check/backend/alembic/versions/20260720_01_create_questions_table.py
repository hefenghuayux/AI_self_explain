"""create questions table

Revision ID: 20260720_01
Revises:
Create Date: 2026-07-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260720_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("question_content", sa.Text(), nullable=False),
        sa.Column("standard_answer", sa.Text(), nullable=False),
        sa.Column("rubric_points", sa.JSON(), nullable=False),
        sa.Column("common_errors", sa.JSON(), nullable=False),
        sa.Column("alternative_solutions", sa.JSON(), nullable=False),
        sa.Column("layered_hints", sa.JSON(), nullable=False),
        sa.Column("full_solution", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("questions")
