"""split TTS voice business catalog from runtime configuration

Revision ID: 20261015_36
Revises: 20261015_35
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261015_36"
down_revision: str | None = "20261015_35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _catalog_values(row: dict) -> dict:
    legacy_subject = row["legacy_subject"]
    if legacy_subject and legacy_subject.startswith(("初中", "高中")):
        education_stage = legacy_subject[:2]
        subject = legacy_subject[2:] or None
    else:
        education_stage = None
        subject = None

    display_name = row["display_name"]
    teacher = row["teacher"]
    name = teacher or display_name
    for suffix in ("_系统女声", "_系统男声", "_引导指令"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break

    is_shiguang_teacher = row["voice_id"].startswith("qwen-") and bool(legacy_subject)
    voice_type = "拾光老师" if is_shiguang_teacher else "自定义"
    remark = f"{education_stage}{subject}" if is_shiguang_teacher and subject else None
    if not is_shiguang_teacher:
        if "女" in display_name:
            remark = "温柔亲和"
        elif "男" in display_name:
            remark = "沉稳自然"

    gender = "女" if "女" in display_name else "男" if "男" in display_name else None
    return {
        "education_stage": education_stage,
        "subject": subject,
        "name": name,
        "remark": remark,
        "gender": gender,
        "voice_type": voice_type,
    }


def upgrade() -> None:
    op.create_table(
        "tts_voice_runtime_configs",
        sa.Column("tts_voice_id", sa.Integer(), nullable=False),
        sa.Column("voice_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column("source_start_seconds", sa.Float(), nullable=True),
        sa.Column("source_end_seconds", sa.Float(), nullable=True),
        sa.Column("source_evidence", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["tts_voice_id"], ["tts_voices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tts_voice_id"),
        sa.UniqueConstraint("voice_id"),
    )

    with op.batch_alter_table("tts_voices") as batch_op:
        batch_op.alter_column(
            "subject",
            new_column_name="legacy_subject",
            existing_type=sa.String(length=50),
            existing_nullable=True,
        )

    with op.batch_alter_table("tts_voices") as batch_op:
        batch_op.add_column(sa.Column("education_stage", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("subject", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("name", sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column("remark", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("gender", sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column("voice_type", sa.String(length=30), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, voice_id, display_name, provider, model, instruction, "
            "legacy_subject, teacher, variant, source_file, source_start_seconds, "
            "source_end_seconds, source_evidence FROM tts_voices"
        )
    ).mappings().all()
    runtime_table = sa.table(
        "tts_voice_runtime_configs",
        sa.column("tts_voice_id", sa.Integer()),
        sa.column("voice_id", sa.String()),
        sa.column("provider", sa.String()),
        sa.column("model", sa.String()),
        sa.column("instruction", sa.Text()),
        sa.column("source_file", sa.Text()),
        sa.column("source_start_seconds", sa.Float()),
        sa.column("source_end_seconds", sa.Float()),
        sa.column("source_evidence", sa.JSON()),
    )
    for row in rows:
        values = _catalog_values(dict(row))
        connection.execute(
            runtime_table.insert().values(
                tts_voice_id=row["id"],
                voice_id=row["voice_id"],
                provider=row["provider"],
                model=row["model"],
                instruction=row["instruction"],
                source_file=row["source_file"],
                source_start_seconds=row["source_start_seconds"],
                source_end_seconds=row["source_end_seconds"],
                source_evidence=(
                    json.loads(row["source_evidence"])
                    if isinstance(row["source_evidence"], str)
                    else row["source_evidence"]
                ),
            )
        )
        connection.execute(
            sa.text(
                "UPDATE tts_voices SET education_stage=:education_stage, subject=:subject, "
                "name=:name, remark=:remark, gender=:gender, voice_type=:voice_type WHERE id=:id"
            ),
            {**values, "id": row["id"]},
        )

    with op.batch_alter_table("tts_voices") as batch_op:
        for column in (
            "voice_id",
            "display_name",
            "provider",
            "model",
            "instruction",
            "legacy_subject",
            "teacher",
            "variant",
            "source_file",
            "source_start_seconds",
            "source_end_seconds",
            "source_evidence",
        ):
            batch_op.drop_column(column)
        batch_op.alter_column(
            "name", existing_type=sa.String(length=150), nullable=False
        )
        batch_op.alter_column(
            "voice_type", existing_type=sa.String(length=30), nullable=False
        )


def downgrade() -> None:
    with op.batch_alter_table("tts_voices") as batch_op:
        batch_op.add_column(sa.Column("voice_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("display_name", sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column("provider", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("model", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("instruction", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("legacy_subject", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("teacher", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("variant", sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column("source_file", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("source_start_seconds", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("source_end_seconds", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("source_evidence", sa.JSON(), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT v.id, v.education_stage, v.subject, v.name, r.voice_id, r.provider, "
            "r.model, r.instruction, r.source_file, r.source_start_seconds, "
            "r.source_end_seconds, r.source_evidence "
            "FROM tts_voices v JOIN tts_voice_runtime_configs r ON r.tts_voice_id=v.id"
        )
    ).mappings().all()
    for row in rows:
        legacy_subject = (
            f"{row['education_stage']}{row['subject']}"
            if row["education_stage"] and row["subject"]
            else None
        )
        connection.execute(
            sa.text(
                "UPDATE tts_voices SET voice_id=:voice_id, display_name=:display_name, "
                "provider=:provider, model=:model, instruction=:instruction, "
                "legacy_subject=:legacy_subject, teacher=:teacher, source_file=:source_file, "
                "source_start_seconds=:source_start_seconds, "
                "source_end_seconds=:source_end_seconds, "
                "source_evidence=:source_evidence WHERE id=:id"
            ),
            {
                **dict(row),
                "display_name": row["name"],
                "teacher": row["name"],
                "legacy_subject": legacy_subject,
            },
        )

    op.drop_table("tts_voice_runtime_configs")
    with op.batch_alter_table("tts_voices") as batch_op:
        batch_op.drop_column("subject")
        batch_op.alter_column(
            "legacy_subject",
            new_column_name="subject",
            existing_type=sa.String(length=50),
            existing_nullable=True,
        )
        for column in ("education_stage", "name", "remark", "gender", "voice_type"):
            batch_op.drop_column(column)
        batch_op.alter_column(
            "voice_id", existing_type=sa.String(length=255), nullable=False
        )
        batch_op.alter_column(
            "display_name", existing_type=sa.String(length=150), nullable=False
        )
        batch_op.alter_column("provider", existing_type=sa.String(length=64), nullable=False)
        batch_op.alter_column("model", existing_type=sa.String(length=128), nullable=False)
        batch_op.alter_column("instruction", existing_type=sa.Text(), nullable=False)
