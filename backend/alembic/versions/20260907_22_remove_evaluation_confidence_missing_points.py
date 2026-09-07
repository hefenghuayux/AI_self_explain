"""remove unused evaluation fields

Revision ID: 20260907_22
Revises: 20260827_21
Create Date: 2026-09-07 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_22"
down_revision: str | None = "20260827_21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ai_evaluations") as batch_op:
        batch_op.drop_column("confidence")
        batch_op.drop_column("missing_points")


def downgrade() -> None:
    with op.batch_alter_table("ai_evaluations") as batch_op:
        batch_op.add_column(sa.Column("missing_points", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("confidence", sa.Float(), nullable=True))
