"""collapse explanation steps to one draft per session round

Revision ID: 20261012_29
Revises: 20260929_28
Create Date: 2026-10-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261012_29"
down_revision: str | None = "20260929_28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("explanation_attempts") as batch_op:
        batch_op.drop_constraint("fk_explanation_attempts_step_id", type_="foreignkey")
        batch_op.drop_index("ix_explanation_attempts_step_id")
        batch_op.drop_column("step_id")
        batch_op.drop_column("structured_steps")
        batch_op.add_column(sa.Column("student_explanation", sa.JSON(), nullable=True))

    with op.batch_alter_table("explanation_steps") as batch_op:
        batch_op.drop_constraint("uq_explanation_steps_session_draft_seq", type_="unique")
        batch_op.drop_constraint("ck_explanation_steps_status", type_="check")
        batch_op.drop_constraint("ck_explanation_steps_seq_positive", type_="check")
        batch_op.drop_index("ix_explanation_steps_session_round_draft")
        batch_op.drop_column("draft_id")
        batch_op.drop_column("seq")
        batch_op.drop_column("status")
        batch_op.create_unique_constraint(
            "uq_explanation_steps_session_round", ["session_id", "round"]
        )


def downgrade() -> None:
    with op.batch_alter_table("explanation_steps") as batch_op:
        batch_op.drop_constraint("uq_explanation_steps_session_round", type_="unique")
        batch_op.add_column(sa.Column("draft_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("seq", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT")
        )
        batch_op.create_check_constraint(
            "ck_explanation_steps_status", "status IN ('DRAFT', 'SAVED', 'SUBMITTED')"
        )
        batch_op.create_check_constraint("ck_explanation_steps_seq_positive", "seq > 0")
        batch_op.create_unique_constraint(
            "uq_explanation_steps_session_draft_seq", ["session_id", "draft_id", "seq"]
        )
        batch_op.create_index(
            "ix_explanation_steps_session_round_draft",
            ["session_id", "round", "draft_id"],
        )

    with op.batch_alter_table("explanation_attempts") as batch_op:
        batch_op.drop_column("student_explanation")
        batch_op.add_column(sa.Column("step_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("structured_steps", sa.JSON(), nullable=True))
        batch_op.create_index("ix_explanation_attempts_step_id", ["step_id"])
        batch_op.create_foreign_key(
            "fk_explanation_attempts_step_id",
            "explanation_steps",
            ["step_id"],
            ["id"],
        )
