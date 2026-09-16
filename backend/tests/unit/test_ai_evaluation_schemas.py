import json

import pytest
from pydantic import ValidationError

from app.schemas.ai_evaluation import (
    AIEvaluationOutput,
    validate_evaluation_relationships,
)


def valid_payload() -> dict[str, object]:
    return {
        "correctness": "CORRECT",
        "completeness": "INCOMPLETE",
        "hasProgress": True,
        "mainReason": "知识应用问题",
        "otherReasons": [],
        "judgeReason": "学生已经给出局部推理，但尚未完成。",
    }


def test_evaluation_schema_rejects_missing_fields_and_unknown_enum() -> None:
    payload = valid_payload()
    payload["correctness"] = "UNKNOWN"

    with pytest.raises(ValidationError):
        AIEvaluationOutput.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("payload_update", "expected_error"),
    [
        ({"mainReason": None}, "mainReason"),
        ({"otherReasons": ["知识应用问题"]}, "不能包含 mainReason"),
    ],
)
def test_evaluation_relationship_validation_rejects_invalid_output(
    payload_update: dict[str, object], expected_error: str
) -> None:
    payload = valid_payload()
    payload.update(payload_update)
    evaluation = AIEvaluationOutput.model_validate(payload)

    errors = validate_evaluation_relationships(evaluation)

    assert any(expected_error in error for error in errors)


@pytest.mark.parametrize(
    "field", ["feedback", "nextAction", "guidedQuestions", "content", "questions"]
)
def test_evaluation_schema_rejects_removed_teaching_fields(field: str) -> None:
    payload = valid_payload()
    payload[field] = "不应存在"

    with pytest.raises(ValidationError):
        AIEvaluationOutput.model_validate(payload)
