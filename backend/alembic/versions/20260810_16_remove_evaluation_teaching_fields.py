"""remove evaluation teaching fields

Revision ID: 20260810_16
Revises: 20260810_15
Create Date: 2026-08-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_16"
down_revision: str | None = "20260810_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ai_evaluations") as batch_op:
        batch_op.drop_column("feedback")
        batch_op.drop_column("next_action")


def downgrade() -> None:
    with op.batch_alter_table("ai_evaluations") as batch_op:
        batch_op.add_column(sa.Column("next_action", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("feedback", sa.Text(), nullable=True))
