"""add audit correlation fields

Revision ID: 20260810_15
Revises: 20260809_14
Create Date: 2026-08-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_15"
down_revision: str | None = "20260809_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("student_submissions") as batch_op:
        batch_op.add_column(sa.Column("request_id", sa.String(length=100), nullable=True))
        batch_op.create_index("ix_student_submissions_request_id", ["request_id"])

    with op.batch_alter_table("support_events") as batch_op:
        batch_op.add_column(sa.Column("request_id", sa.String(length=100), nullable=True))
        batch_op.create_index("ix_support_events_request_id", ["request_id"])

    with op.batch_alter_table("state_transition_events") as batch_op:
        batch_op.add_column(sa.Column("related_support_event_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            "ix_state_transition_events_related_support_event_id",
            ["related_support_event_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("state_transition_events") as batch_op:
        batch_op.drop_index("ix_state_transition_events_related_support_event_id")
        batch_op.drop_column("related_support_event_id")

    with op.batch_alter_table("support_events") as batch_op:
        batch_op.drop_index("ix_support_events_request_id")
        batch_op.drop_column("request_id")

    with op.batch_alter_table("student_submissions") as batch_op:
        batch_op.drop_index("ix_student_submissions_request_id")
        batch_op.drop_column("request_id")
