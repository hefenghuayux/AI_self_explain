"""remove covered_points and error_evidence columns from ai_evaluations and sessions

Revision ID: 20260907_24
Revises: 20260907_23
Create Date: 2026-09-07 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_24"
down_revision: str | None = "20260907_23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ai_evaluations") as batch_op:
        batch_op.drop_column("covered_points")
        batch_op.drop_column("error_evidence")
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_column("covered_points_current_round")
        batch_op.drop_column("covered_points_all")


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.add_column(
            sa.Column("covered_points_all", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.alter_column("covered_points_all", server_default=None)
        batch_op.add_column(
            sa.Column("covered_points_current_round", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.alter_column("covered_points_current_round", server_default=None)
    with op.batch_alter_table("ai_evaluations") as batch_op:
        batch_op.add_column(sa.Column("error_evidence", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("covered_points", sa.JSON(), nullable=True))