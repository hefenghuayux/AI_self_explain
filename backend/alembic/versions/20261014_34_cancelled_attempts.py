"""mark cancelled explanation attempts

Revision ID: 20261014_34
Revises: 20261014_33
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261014_34"
down_revision: str | None = "20261014_33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "explanation_attempts", sa.Column("cancelled_run_id", sa.String(64), nullable=True)
    )
    op.create_index(
        "ix_explanation_attempts_cancelled_run_id",
        "explanation_attempts", ["cancelled_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_explanation_attempts_cancelled_run_id", table_name="explanation_attempts")
    op.drop_column("explanation_attempts", "cancelled_run_id")
