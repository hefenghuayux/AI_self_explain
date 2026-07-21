"""add request id to external call records"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260721_09"
down_revision: str | None = "20260721_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("external_call_records") as batch_op:
        batch_op.add_column(sa.Column("request_id", sa.String(length=100), nullable=True))
        batch_op.create_index("ix_external_call_records_request_id", ["request_id"])


def downgrade() -> None:
    with op.batch_alter_table("external_call_records") as batch_op:
        batch_op.drop_index("ix_external_call_records_request_id")
        batch_op.drop_column("request_id")
