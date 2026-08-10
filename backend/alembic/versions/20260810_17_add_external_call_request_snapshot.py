"""add external call request snapshot

Revision ID: 20260810_17
Revises: 20260810_16
Create Date: 2026-08-10 00:00:00.000000

Downgrade restores the legacy status from transport_status. Validation state cannot be
represented by the old schema and is intentionally discarded.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_17"
down_revision: str | None = "20260810_16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("external_call_records") as batch_op:
        batch_op.add_column(sa.Column("transport_status", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("validation_status", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("validation_errors", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("request_snapshot", sa.JSON(), nullable=True))

    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE external_call_records SET transport_status = status")
    )
    connection.execute(
        sa.text(
            "UPDATE external_call_records "
            "SET transport_status = 'SUCCESS', validation_status = 'INVALID', "
            "validation_errors = json_array(error_message) "
            "WHERE call_type != 'ASR' AND error_type = 'AI_SCHEMA_ERROR'"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE external_call_records SET validation_status = 'NOT_RUN' "
            "WHERE validation_status IS NULL AND (call_type = 'ASR' OR status = 'ERROR')"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE external_call_records SET validation_status = 'UNKNOWN' "
            "WHERE validation_status IS NULL"
        )
    )

    with op.batch_alter_table("external_call_records") as batch_op:
        batch_op.alter_column("transport_status", existing_type=sa.String(length=30), nullable=False)
        batch_op.alter_column("validation_status", existing_type=sa.String(length=30), nullable=False)
        batch_op.drop_column("status")

    with op.batch_alter_table("ai_evaluations") as batch_op:
        batch_op.add_column(sa.Column("external_call_record_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            "ix_ai_evaluations_external_call_record_id", ["external_call_record_id"]
        )
        batch_op.create_foreign_key(
            "fk_ai_evaluations_external_call_record_id",
            "external_call_records",
            ["external_call_record_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_evaluations") as batch_op:
        batch_op.drop_constraint(
            "fk_ai_evaluations_external_call_record_id", type_="foreignkey"
        )
        batch_op.drop_index("ix_ai_evaluations_external_call_record_id")
        batch_op.drop_column("external_call_record_id")

    with op.batch_alter_table("external_call_records") as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(length=30), nullable=True))

    connection = op.get_bind()
    connection.execute(sa.text("UPDATE external_call_records SET status = transport_status"))

    with op.batch_alter_table("external_call_records") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(length=30), nullable=False)
        batch_op.drop_column("request_snapshot")
        batch_op.drop_column("validation_errors")
        batch_op.drop_column("validation_status")
        batch_op.drop_column("transport_status")
