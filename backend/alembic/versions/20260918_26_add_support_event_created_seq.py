"""add support event created seq

Revision ID: 20260918_26
Revises: 20260918_25
Create Date: 2026-09-18 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260918_26"
down_revision: str | None = "20260918_25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 记录支持事件创建时的 session_events.seq，供上下文历史按事件序排序。
    # 历史行无法回填（当时没有事件日志），保持 NULL，由读取侧回退 created_at。
    with op.batch_alter_table("support_events") as batch_op:
        batch_op.add_column(sa.Column("created_seq", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("support_events") as batch_op:
        batch_op.drop_column("created_seq")
