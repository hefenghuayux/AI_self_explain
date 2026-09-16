"""convert evaluation covered point labels to indexes

Revision ID: 20260907_23
Revises: 20260907_22
Create Date: 2026-09-07 00:00:00.000000
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_23"
down_revision: str | None = "20260907_22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    evaluations = sa.table(
        "ai_evaluations",
        sa.column("id", sa.Integer),
        sa.column("session_id", sa.Integer),
        sa.column("covered_points", sa.JSON),
    )
    sessions = sa.table(
        "sessions",
        sa.column("id", sa.Integer),
        sa.column("question_id", sa.Integer),
    )
    questions = sa.table(
        "self_explain_questions",
        sa.column("id", sa.Integer),
        sa.column("rubric_points", sa.JSON),
    )
    rows = connection.execute(
        sa.select(evaluations.c.id, evaluations.c.session_id, evaluations.c.covered_points)
        .select_from(
            evaluations.join(sessions, evaluations.c.session_id == sessions.c.id).join(
                questions, sessions.c.question_id == questions.c.id
            )
        )
    )
    for evaluation_id, session_id, covered_points in rows:
        if not covered_points:
            continue
        points = json.loads(covered_points) if isinstance(covered_points, str) else covered_points
        if not isinstance(points, list) or not points or not isinstance(points[0], str):
            continue
        rubric = connection.execute(
            sa.select(questions.c.rubric_points).select_from(
                questions.join(sessions, questions.c.id == sessions.c.question_id)
            ).where(sessions.c.id == session_id)
        ).scalar_one()
        rubric = json.loads(rubric) if isinstance(rubric, str) else rubric
        indexes = [rubric.index(point) + 1 for point in points]
        connection.execute(
            evaluations.update()
            .where(evaluations.c.id == evaluation_id)
            .values(covered_points=indexes)
        )


def downgrade() -> None:
    # 保留编号数据；回滚版本仅用于测试旧表结构，无法恢复已删除的字段。
    pass
