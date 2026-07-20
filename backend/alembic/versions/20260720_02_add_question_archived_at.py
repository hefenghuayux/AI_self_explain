"""add question archived at

Revision ID: 20260720_02
Revises: 20260720_01
Create Date: 2026-07-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260720_02"
down_revision: str | None = "20260720_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_questions_archived_at", "questions", ["archived_at"])


def downgrade() -> None:
    op.drop_index("ix_questions_archived_at", table_name="questions")
    op.drop_column("questions", "archived_at")
