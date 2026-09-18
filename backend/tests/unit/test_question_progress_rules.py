from app.rules.question_progress import (
    PROGRESS_ATTEMPTED,
    PROGRESS_COMPLETED,
    PROGRESS_NOT_ATTEMPTED,
    question_progress,
)


def test_completed_session_wins_over_submitted_attempt() -> None:
    assert question_progress(has_completed=True, has_attempt=True) == PROGRESS_COMPLETED


def test_submitted_attempt_without_completed_session_is_attempted() -> None:
    assert question_progress(has_completed=False, has_attempt=True) == PROGRESS_ATTEMPTED


def test_session_without_submitted_attempt_is_not_attempted() -> None:
    assert question_progress(has_completed=False, has_attempt=False) == PROGRESS_NOT_ATTEMPTED
