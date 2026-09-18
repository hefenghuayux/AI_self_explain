"""remove NEED_HUMAN legacy

Revision ID: 20260918_25
Revises: 20260907_24
Create Date: 2026-09-18 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260918_25"
down_revision: str | None = "20260907_24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 早期版本会把会话直接置为 NEED_HUMAN；后续版本统一保持 IN_PROGRESS，只记录原因。
    op.execute("UPDATE sessions SET status = 'IN_PROGRESS' WHERE status = 'NEED_HUMAN'")
    with op.batch_alter_table("ai_evaluations") as batch_op:
        batch_op.drop_column("need_human_reason")


def downgrade() -> None:
    with op.batch_alter_table("ai_evaluations") as batch_op:
        batch_op.add_column(sa.Column("need_human_reason", sa.Text(), nullable=True))
    # sessions.status 的历史取值无法还原：无法确定哪些会话曾经是 NEED_HUMAN。