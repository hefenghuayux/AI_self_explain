"""add question guided questions

Revision ID: 20260721_07
Revises: 20260721_06
Create Date: 2026-07-21 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260721_07"
down_revision: str | None = "20260721_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("guided_questions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("questions", "guided_questions")
