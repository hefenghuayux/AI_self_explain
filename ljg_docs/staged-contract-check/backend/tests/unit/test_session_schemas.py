import pytest
from pydantic import ValidationError

from app.schemas.session import (
    TeachingNotRequiredResponse,
    TeachingSucceededResponse,
    TextAttemptInput,
)


def test_text_attempt_rejects_blank_confirmed_text() -> None:
    with pytest.raises(ValidationError, match="String should have at least 1 character"):
        TextAttemptInput(confirmedText="   ", version=0)


def test_text_attempt_uses_camel_case_input() -> None:
    attempt = TextAttemptInput(confirmedText="我先计算 1 加 1", version=2)

    assert attempt.confirmed_text == "我先计算 1 加 1"
    assert attempt.version == 2


def test_teaching_generation_response_serializes_transient_support_reference() -> None:
    result = TeachingSucceededResponse(status="SUCCEEDED", supportEventId=9)

    assert result.model_dump(by_alias=True) == {
        "status": "SUCCEEDED",
        "supportEventId": 9,
    }

    not_required = TeachingNotRequiredResponse(status="NOT_REQUIRED")
    assert not_required.model_dump(by_alias=True) == {"status": "NOT_REQUIRED"}
