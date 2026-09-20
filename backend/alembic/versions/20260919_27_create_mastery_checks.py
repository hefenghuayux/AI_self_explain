"""create mastery checks

Revision ID: 20260919_27
Revises: 20260918_26
Create Date: 2026-09-19 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260919_27"
down_revision: str | None = "20260918_26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 一次对话后核验一行：questions 在生成时写入，answers/results/outcome 在提交时补齐。
    # 历史会话没有核验记录，读取侧按“无核验”处理，不做回填。
    op.create_table(
        "mastery_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("evaluation_id", sa.Integer(), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=True),
        sa.Column("results", sa.JSON(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["attempt_id"], ["explanation_attempts.id"]),
        sa.ForeignKeyConstraint(["evaluation_id"], ["ai_evaluations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mastery_checks_session_id", "mastery_checks", ["session_id"])
    op.create_index("ix_mastery_checks_attempt_id", "mastery_checks", ["attempt_id"])
    op.create_index("ix_mastery_checks_evaluation_id", "mastery_checks", ["evaluation_id"])


def downgrade() -> None:
    op.drop_index("ix_mastery_checks_evaluation_id", table_name="mastery_checks")
    op.drop_index("ix_mastery_checks_attempt_id", table_name="mastery_checks")
    op.drop_index("ix_mastery_checks_session_id", table_name="mastery_checks")
    op.drop_table("mastery_checks")
