"""add user role constraint

Revision ID: 20260722_11
Revises: 20260722_10
Create Date: 2026-07-22 00:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260722_11"
down_revision: str | None = "20260722_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_check_constraint(
            "ck_users_role", "role IN ('STUDENT', 'TEACHER')"
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_role", type_="check")
