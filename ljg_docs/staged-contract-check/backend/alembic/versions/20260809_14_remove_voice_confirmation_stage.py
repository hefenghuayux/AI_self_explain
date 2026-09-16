"""remove voice confirmation stage

Revision ID: 20260809_14
Revises: 20260802_13
Create Date: 2026-08-09 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260809_14"
down_revision: str | None = "20260802_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE sessions
        SET current_draft = (
            SELECT attempt.asr_transcript
            FROM explanation_attempts AS attempt
            WHERE attempt.session_id = sessions.id
              AND attempt.input_mode = 'VOICE'
              AND attempt.confirmed_text IS NULL
              AND attempt.voice_target = 'SELF_EXPLANATION'
            ORDER BY attempt.id DESC
            LIMIT 1
        )
        WHERE flow_stage = 'CONFIRMING_TEXT'
          AND current_draft = ''
          AND EXISTS (
            SELECT 1
            FROM explanation_attempts AS attempt
            WHERE attempt.session_id = sessions.id
              AND attempt.input_mode = 'VOICE'
              AND attempt.confirmed_text IS NULL
              AND attempt.voice_target = 'SELF_EXPLANATION'
          )
        """
    )
    for column in ("flow_stage", "paused_from_stage"):
        op.execute(
            f"""
            UPDATE sessions
            SET {column} = CASE
                WHEN EXISTS (
                    SELECT 1 FROM explanation_attempts AS attempt
                    WHERE attempt.session_id = sessions.id
                      AND attempt.input_mode = 'VOICE'
                      AND attempt.confirmed_text IS NULL
                      AND attempt.voice_target = 'GUIDED_ANSWER'
                ) THEN 'WAIT_GUIDED_ANSWERS'
                WHEN EXISTS (
                    SELECT 1 FROM explanation_attempts AS attempt
                    WHERE attempt.session_id = sessions.id
                      AND attempt.input_mode = 'VOICE'
                      AND attempt.confirmed_text IS NULL
                      AND attempt.voice_target IN ('DOUBT', 'APPEAL')
                ) THEN 'WAIT_STUDENT_ACTION'
                WHEN EXISTS (
                    SELECT 1 FROM explanation_attempts AS attempt
                    WHERE attempt.session_id = sessions.id
                      AND attempt.input_mode = 'VOICE'
                      AND attempt.confirmed_text IS NULL
                      AND attempt.voice_target = 'SELF_EXPLANATION'
                ) THEN 'CAPTURING_INPUT'
                ELSE 'WAIT_STUDENT_ACTION'
            END
            WHERE {column} = 'CONFIRMING_TEXT'
            """
        )


def downgrade() -> None:
    pass
