"""create explanation steps and structured voice fields

Revision ID: 20260929_28
Revises: 20260919_27
Create Date: 2026-09-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260929_28"
down_revision: str | None = "20260919_27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "explanation_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("step_content", sa.Text(), nullable=True),
        sa.Column("explain_transcript", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'SAVED', 'SUBMITTED')",
            name="ck_explanation_steps_status",
        ),
        sa.CheckConstraint("seq > 0", name="ck_explanation_steps_seq_positive"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "draft_id",
            "seq",
            name="uq_explanation_steps_session_draft_seq",
        ),
    )
    op.create_index("ix_explanation_steps_session_id", "explanation_steps", ["session_id"])
    op.create_index(
        "ix_explanation_steps_session_round_draft",
        "explanation_steps",
        ["session_id", "round", "draft_id"],
    )

    with op.batch_alter_table("explanation_attempts") as batch_op:
        batch_op.add_column(sa.Column("step_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("structured_steps", sa.JSON(), nullable=True))
        batch_op.create_index("ix_explanation_attempts_step_id", ["step_id"])
        batch_op.create_foreign_key(
            "fk_explanation_attempts_step_id",
            "explanation_steps",
            ["step_id"],
            ["id"],
        )

    with op.batch_alter_table("sessions") as batch_op:
        batch_op.add_column(sa.Column("current_step_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_sessions_current_step_id", ["current_step_id"])
        batch_op.create_foreign_key(
            "fk_sessions_current_step_id",
            "explanation_steps",
            ["current_step_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_constraint("fk_sessions_current_step_id", type_="foreignkey")
        batch_op.drop_index("ix_sessions_current_step_id")
        batch_op.drop_column("current_step_id")

    with op.batch_alter_table("explanation_attempts") as batch_op:
        batch_op.drop_constraint("fk_explanation_attempts_step_id", type_="foreignkey")
        batch_op.drop_index("ix_explanation_attempts_step_id")
        batch_op.drop_column("structured_steps")
        batch_op.drop_column("step_id")

    op.drop_index(
        "ix_explanation_steps_session_round_draft",
        table_name="explanation_steps",
    )
    op.drop_index("ix_explanation_steps_session_id", table_name="explanation_steps")
    op.drop_table("explanation_steps")
