"""allow large AI provider responses in audit records

Revision ID: 20261015_35
Revises: 20261014_34
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "20261015_35"
down_revision: str | None = "20261014_34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LONGTEXT = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


def upgrade() -> None:
    for table_name in ("external_call_records", "ai_evaluations"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "raw_response",
                existing_type=sa.Text(),
                type_=_LONGTEXT,
                existing_nullable=True,
            )


def downgrade() -> None:
    for table_name in ("external_call_records", "ai_evaluations"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "raw_response",
                existing_type=_LONGTEXT,
                type_=sa.Text(),
                existing_nullable=True,
            )
