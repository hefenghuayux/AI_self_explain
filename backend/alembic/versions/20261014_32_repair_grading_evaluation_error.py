"""repair revision 31 databases missing the evaluation error column

Revision ID: 20261014_32
Revises: 20261013_31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261014_32"
down_revision: str | None = "20261013_31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        column["name"]: column
        for column in sa.inspect(op.get_bind()).get_columns("first_explanation_gradings")
    }
    column = columns.get("evaluation_error")
    if column is None:
        # 旧库已登记 revision 31；重复执行原建表迁移无法补上这列。
        op.add_column(
            "first_explanation_gradings", sa.Column("evaluation_error", sa.Text(), nullable=True)
        )
    elif not isinstance(column["type"], sa.Text) or not column["nullable"]:
        raise RuntimeError("evaluation_error 必须是可空 TEXT 列，停止迁移")


def downgrade() -> None:
    # 当前 revision 31 的建表定义也包含这列。回退仅退版本号，保留修复列及错误信息。
    pass
