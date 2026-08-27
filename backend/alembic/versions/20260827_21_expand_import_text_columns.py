"""expand imported text columns

Revision ID: 20260827_21
Revises: 20260827_20
Create Date: 2026-08-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_21"
down_revision: str | None = "20260827_20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMPORT_TEXT_LENGTH = 16_777_215


def upgrade() -> None:
    with op.batch_alter_table("self_explain_questions") as batch_op:
        batch_op.alter_column(
            "question_content",
            existing_type=sa.Text(),
            type_=sa.Text(length=IMPORT_TEXT_LENGTH),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "standard_answer",
            existing_type=sa.Text(),
            type_=sa.Text(length=IMPORT_TEXT_LENGTH),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "full_solution",
            existing_type=sa.Text(),
            type_=sa.Text(length=IMPORT_TEXT_LENGTH),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "topics",
            existing_type=sa.Text(),
            type_=sa.Text(length=IMPORT_TEXT_LENGTH),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "method",
            existing_type=sa.Text(),
            type_=sa.Text(length=IMPORT_TEXT_LENGTH),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("self_explain_questions") as batch_op:
        batch_op.alter_column(
            "method",
            existing_type=sa.Text(length=IMPORT_TEXT_LENGTH),
            type_=sa.Text(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "topics",
            existing_type=sa.Text(length=IMPORT_TEXT_LENGTH),
            type_=sa.Text(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "full_solution",
            existing_type=sa.Text(length=IMPORT_TEXT_LENGTH),
            type_=sa.Text(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "standard_answer",
            existing_type=sa.Text(length=IMPORT_TEXT_LENGTH),
            type_=sa.Text(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "question_content",
            existing_type=sa.Text(length=IMPORT_TEXT_LENGTH),
            type_=sa.Text(),
            existing_nullable=False,
        )
