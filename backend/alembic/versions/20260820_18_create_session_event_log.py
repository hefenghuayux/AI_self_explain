"""create session event log

Revision ID: 20260820_18
Revises: 20260810_17
Create Date: 2026-08-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260820_18"
down_revision: str | None = "20260810_17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "lifecycle_status",
                sa.String(length=20),
                server_default="active",
                nullable=False,
            )
        )
        batch_op.create_index("ix_sessions_parent_id", ["parent_id"])
        batch_op.create_foreign_key("fk_sessions_parent_id", "sessions", ["parent_id"], ["id"])
        batch_op.create_check_constraint(
            "ck_sessions_lifecycle_status",
            "lifecycle_status IN ('active', 'completed', 'failed')",
        )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE sessions SET lifecycle_status = 'completed' "
            "WHERE status IN ('COMPLETED', 'STOPPED_LIMIT')"
        )
    )

    op.create_table(
        "session_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("parent_event_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.CheckConstraint("seq >= 0", name="ck_session_events_seq_non_negative"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_session_events_event_id"),
        sa.UniqueConstraint("session_id", "seq", name="uq_session_events_session_seq"),
    )
    op.create_index("ix_session_events_session_id_seq", "session_events", ["session_id", "seq"])
    op.create_index(
        "ix_session_events_session_run_seq",
        "session_events",
        ["session_id", "run_id", "seq"],
    )
    op.create_index(
        "ix_session_events_session_type_seq",
        "session_events",
        ["session_id", "event_type", "seq"],
    )

    sessions = connection.execute(sa.text("SELECT id, created_at FROM sessions")).mappings()
    event_table = sa.table(
        "session_events",
        sa.column("session_id", sa.Integer()),
        sa.column("seq", sa.Integer()),
        sa.column("event_id", sa.String()),
        sa.column("run_id", sa.String()),
        sa.column("parent_event_id", sa.String()),
        sa.column("event_type", sa.String()),
        sa.column("occurred_at", sa.DateTime(timezone=True)),
        sa.column("data", sa.JSON()),
    )
    for session in sessions:
        connection.execute(
            event_table.insert().values(
                session_id=session["id"],
                seq=0,
                event_id=f"evt_migrated_session_{session['id']}_started",
                run_id=None,
                parent_event_id=None,
                event_type="session.started",
                occurred_at=session["created_at"],
                data={},
            )
        )


def downgrade() -> None:
    op.drop_index("ix_session_events_session_type_seq", table_name="session_events")
    op.drop_index("ix_session_events_session_run_seq", table_name="session_events")
    op.drop_index("ix_session_events_session_id_seq", table_name="session_events")
    op.drop_table("session_events")

    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_constraint("ck_sessions_lifecycle_status", type_="check")
        batch_op.drop_constraint("fk_sessions_parent_id", type_="foreignkey")
        batch_op.drop_index("ix_sessions_parent_id")
        batch_op.drop_column("lifecycle_status")
        batch_op.drop_column("parent_id")
