"""add voice input target

Revision ID: 20260802_13
Revises: 20260722_12
Create Date: 2026-08-02 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_13"
down_revision: str | None = "20260722_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "explanation_attempts", sa.Column("voice_target", sa.String(length=30), nullable=True)
    )
    op.add_column(
        "explanation_attempts", sa.Column("voice_target_id", sa.String(length=100), nullable=True)
    )
    op.execute(
        "UPDATE explanation_attempts SET voice_target = 'SELF_EXPLANATION' "
        "WHERE input_mode = 'VOICE'"
    )


def downgrade() -> None:
    op.drop_column("explanation_attempts", "voice_target_id")
    op.drop_column("explanation_attempts", "voice_target")
