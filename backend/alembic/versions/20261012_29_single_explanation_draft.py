"""collapse explanation steps to one draft per session round

Revision ID: 20261012_29
Revises: 20260929_28
Create Date: 2026-10-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261012_29"
down_revision: str | None = "20260929_28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    duplicates = connection.execute(
        sa.text(
            "SELECT session_id, round, COUNT(*) AS records FROM explanation_steps "
            "GROUP BY session_id, round HAVING COUNT(*) > 1 LIMIT 10"
        )
    ).all()
    if duplicates:
        raise RuntimeError(
            f"存在重复的会话轮次草稿，停止迁移；请先备份并明确保留记录：{duplicates}"
        )

    attempt_columns = {column["name"] for column in inspector.get_columns("explanation_attempts")}
    attempt_foreign_keys = inspector.get_foreign_keys("explanation_attempts")
    attempt_indexes = {index["name"] for index in inspector.get_indexes("explanation_attempts")}
    step_columns = {column["name"] for column in inspector.get_columns("explanation_steps")}
    step_unique_constraints = {
        constraint["name"]: constraint["column_names"]
        for constraint in inspector.get_unique_constraints("explanation_steps")
    }
    step_checks = {
        constraint["name"] for constraint in inspector.get_check_constraints("explanation_steps")
    }
    step_indexes = {index["name"] for index in inspector.get_indexes("explanation_steps")}
    target_unique = "uq_explanation_steps_session_round"
    if target_unique in step_unique_constraints and step_unique_constraints[target_unique] != [
        "session_id",
        "round",
    ]:
        raise RuntimeError(f"唯一约束 {target_unique} 的列不符合预期，停止迁移")
    for foreign_key in attempt_foreign_keys:
        if "step_id" in foreign_key["constrained_columns"] and (
            foreign_key["constrained_columns"] != ["step_id"]
            or foreign_key["referred_table"] != "explanation_steps"
            or foreign_key["referred_columns"] != ["id"]
            or not foreign_key["name"]
        ):
            raise RuntimeError("step_id 外键结构不符合预期，停止迁移")

    # MySQL DDL 不随事务回滚；重试时按真实结构继续，版本仅由 Alembic 在成功后更新。
    with op.batch_alter_table("explanation_attempts") as batch_op:
        for foreign_key in attempt_foreign_keys:
            if foreign_key["constrained_columns"] == ["step_id"]:
                batch_op.drop_constraint(foreign_key["name"], type_="foreignkey")
        if "ix_explanation_attempts_step_id" in attempt_indexes:
            batch_op.drop_index("ix_explanation_attempts_step_id")
        for column in ("step_id", "structured_steps"):
            if column in attempt_columns:
                batch_op.drop_column(column)
        if "student_explanation" not in attempt_columns:
            batch_op.add_column(sa.Column("student_explanation", sa.JSON(), nullable=True))

    with op.batch_alter_table("explanation_steps") as batch_op:
        if "uq_explanation_steps_session_draft_seq" in step_unique_constraints:
            batch_op.drop_constraint("uq_explanation_steps_session_draft_seq", type_="unique")
        for constraint in ("ck_explanation_steps_status", "ck_explanation_steps_seq_positive"):
            if constraint in step_checks:
                batch_op.drop_constraint(constraint, type_="check")
        if "ix_explanation_steps_session_round_draft" in step_indexes:
            batch_op.drop_index("ix_explanation_steps_session_round_draft")
        for column in ("draft_id", "seq", "status"):
            if column in step_columns:
                batch_op.drop_column(column)
        if target_unique not in step_unique_constraints:
            batch_op.create_unique_constraint(target_unique, ["session_id", "round"])


def downgrade() -> None:
    with op.batch_alter_table("explanation_steps") as batch_op:
        batch_op.drop_constraint("uq_explanation_steps_session_round", type_="unique")
        batch_op.add_column(sa.Column("draft_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("seq", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT")
        )
        batch_op.create_check_constraint(
            "ck_explanation_steps_status", "status IN ('DRAFT', 'SAVED', 'SUBMITTED')"
        )
        batch_op.create_check_constraint("ck_explanation_steps_seq_positive", "seq > 0")
        batch_op.create_unique_constraint(
            "uq_explanation_steps_session_draft_seq", ["session_id", "draft_id", "seq"]
        )
        batch_op.create_index(
            "ix_explanation_steps_session_round_draft",
            ["session_id", "round", "draft_id"],
        )

    with op.batch_alter_table("explanation_attempts") as batch_op:
        batch_op.drop_column("student_explanation")
        batch_op.add_column(sa.Column("step_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("structured_steps", sa.JSON(), nullable=True))
        batch_op.create_index("ix_explanation_attempts_step_id", ["step_id"])
        batch_op.create_foreign_key(
            "fk_explanation_attempts_step_id",
            "explanation_steps",
            ["step_id"],
            ["id"],
        )
