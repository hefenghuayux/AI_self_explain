import json

import pytest
from pydantic import ValidationError

from app.schemas.ai_evaluation import (
    AIEvaluationOutput,
    evaluation_json_schema,
    validate_evaluation_relationships,
)


def valid_payload() -> dict[str, object]:
    return {
        "correctness": "CORRECT",
        "completeness": "INCOMPLETE",
        "coveredPoints": ["正确计算加法"],
        "missingPoints": ["得出结果 2"],
        "errorEvidence": [],
        "confidence": 1,
        "needHumanReason": None,
    }


def test_evaluation_schema_uses_the_original_rubric_points_as_dynamic_enum() -> None:
    schema = evaluation_json_schema(["正确计算加法", "得出结果 2"])
    properties = schema["properties"]

    assert properties["coveredPoints"]["items"]["enum"] == ["正确计算加法", "得出结果 2"]
    assert properties["missingPoints"]["items"]["enum"] == ["正确计算加法", "得出结果 2"]
    assert schema["additionalProperties"] is False


def test_evaluation_schema_rejects_missing_fields_and_unknown_enum() -> None:
    payload = valid_payload()
    payload["correctness"] = "UNKNOWN"
    del payload["confidence"]

    with pytest.raises(ValidationError):
        AIEvaluationOutput.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("payload_update", "expected_error"),
    [
        ({"coveredPoints": ["未知评分点"], "missingPoints": ["得出结果 2"]}, "完整覆盖"),
        ({"coveredPoints": ["正确计算加法"], "missingPoints": ["正确计算加法"]}, "不能重叠"),
        ({"correctness": "UNCERTAIN", "needHumanReason": None}, "needHumanReason 必填"),
        ({"needHumanReason": "不确定"}, "必须为空"),
        (
            {
                "correctness": "WRONG",
                "completeness": "COMPLETE",
                "errorEvidence": [
                    {
                        "quote": "不存在的原文",
                        "locationDescription": "第一句",
                        "reason": "计算错误",
                        "thinkingDirection": "重新计算",
                    }
                ],
            },
            "confirmedText 中的原文",
        ),
    ],
)
def test_evaluation_relationship_validation_rejects_invalid_output(
    payload_update: dict[str, object], expected_error: str
) -> None:
    payload = valid_payload()
    payload.update(payload_update)
    evaluation = AIEvaluationOutput.model_validate(payload)

    errors = validate_evaluation_relationships(
        evaluation,
        ["正确计算加法", "得出结果 2"],
        "我先计算 1 加 1。",
    )

    assert any(expected_error in error for error in errors)


@pytest.mark.parametrize("field", ["feedback", "nextAction", "guidedQuestions"])
def test_evaluation_schema_rejects_removed_teaching_fields(field: str) -> None:
    payload = valid_payload()
    payload[field] = "不应存在"

    with pytest.raises(ValidationError):
        AIEvaluationOutput.model_validate(payload)
