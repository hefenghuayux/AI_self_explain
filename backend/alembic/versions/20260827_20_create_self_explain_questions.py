"""create self explain questions

Revision ID: 20260827_20
Revises: 20260826_19
Create Date: 2026-08-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_20"
down_revision: str | None = "20260826_19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("questions", "self_explain_questions")
    with op.batch_alter_table("self_explain_questions") as batch_op:
        batch_op.add_column(sa.Column("tiku_question_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("grade_period", sa.SmallInteger(), nullable=True))
        batch_op.add_column(sa.Column("subject", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("q_type", sa.SmallInteger(), nullable=True))
        batch_op.add_column(sa.Column("difficulty_level", sa.SmallInteger(), nullable=True))
        batch_op.add_column(sa.Column("review", sa.String(length=2048), nullable=True))
        batch_op.add_column(sa.Column("topics", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("method", sa.Text(), nullable=True))
        batch_op.alter_column("standard_answer", existing_type=sa.Text(), nullable=True)
        batch_op.alter_column("rubric_points", existing_type=sa.JSON(), nullable=True)
        batch_op.alter_column("common_errors", existing_type=sa.JSON(), nullable=True)
        batch_op.alter_column("alternative_solutions", existing_type=sa.JSON(), nullable=True)
        batch_op.alter_column("layered_hints", existing_type=sa.JSON(), nullable=True)
        batch_op.alter_column("guided_questions", existing_type=sa.JSON(), nullable=True)
        batch_op.alter_column("full_solution", existing_type=sa.Text(), nullable=True)
        batch_op.create_unique_constraint(
            "uq_self_explain_questions_tiku_question_id", ["tiku_question_id"]
        )
    op.add_column(
        "ai_evaluations",
        sa.Column(
            "evaluation_mode",
            sa.String(length=20),
            nullable=False,
            server_default="FULL_RUBRIC",
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_evaluations", "evaluation_mode")
    with op.batch_alter_table("self_explain_questions") as batch_op:
        batch_op.drop_constraint("uq_self_explain_questions_tiku_question_id", type_="unique")
        batch_op.alter_column("full_solution", existing_type=sa.Text(), nullable=False)
        batch_op.alter_column("guided_questions", existing_type=sa.JSON(), nullable=False)
        batch_op.alter_column("layered_hints", existing_type=sa.JSON(), nullable=False)
        batch_op.alter_column("alternative_solutions", existing_type=sa.JSON(), nullable=False)
        batch_op.alter_column("common_errors", existing_type=sa.JSON(), nullable=False)
        batch_op.alter_column("rubric_points", existing_type=sa.JSON(), nullable=False)
        batch_op.alter_column("standard_answer", existing_type=sa.Text(), nullable=False)
        batch_op.drop_column("method")
        batch_op.drop_column("topics")
        batch_op.drop_column("review")
        batch_op.drop_column("difficulty_level")
        batch_op.drop_column("q_type")
        batch_op.drop_column("subject")
        batch_op.drop_column("grade_period")
        batch_op.drop_column("tiku_question_id")
    op.rename_table("self_explain_questions", "questions")
