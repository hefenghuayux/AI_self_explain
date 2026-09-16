"""add session user and restart state

Revision ID: 20260826_19
Revises: 20260820_18
Create Date: 2026-08-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_19"
down_revision: str | None = "20260820_18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_constraint("ck_sessions_lifecycle_status", type_="check")
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_sessions_user_id", ["user_id"])
        batch_op.create_foreign_key("fk_sessions_user_id", "users", ["user_id"], ["id"])
        batch_op.create_check_constraint(
            "ck_sessions_lifecycle_status",
            "lifecycle_status IN ('active', 'completed', 'failed', 'restarted')",
        )


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_constraint("ck_sessions_lifecycle_status", type_="check")
        batch_op.drop_constraint("fk_sessions_user_id", type_="foreignkey")
        batch_op.drop_index("ix_sessions_user_id")
        batch_op.drop_column("user_id")
        batch_op.create_check_constraint(
            "ck_sessions_lifecycle_status",
            "lifecycle_status IN ('active', 'completed', 'failed')",
        )
