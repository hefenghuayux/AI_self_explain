import json
import logging

import pytest
from pydantic import ValidationError

from app.schemas.ai_evaluation import (
    LEGACY_EVALUATION_FIELDS,
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


def collect_evaluation_schema_logs(action: object) -> list[logging.LogRecord]:
    """直接挂在模块 logger 上收集记录，避免 root handler 被其他测试清空。"""
    records: list[logging.LogRecord] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("app.schemas.ai_evaluation")
    handler = Collector()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        action()
    finally:
        logger.setLevel(previous_level)
        logger.removeHandler(handler)
    return records


def test_evaluation_schema_discards_legacy_fields_and_logs_warning() -> None:
    payload = valid_payload()
    payload.update(dict.fromkeys(LEGACY_EVALUATION_FIELDS, "旧契约字段"))
    evaluation: AIEvaluationOutput | None = None

    def validate() -> None:
        nonlocal evaluation
        evaluation = AIEvaluationOutput.model_validate(payload)

    records = collect_evaluation_schema_logs(validate)

    assert evaluation is not None
    assert evaluation.main_reason == "知识应用问题"
    assert [record.eventName for record in records] == ["ai.output.legacy_fields_discarded"]
    assert records[0].legacyFields == ",".join(LEGACY_EVALUATION_FIELDS)


def test_evaluation_schema_stays_silent_without_legacy_fields() -> None:
    records = collect_evaluation_schema_logs(
        lambda: AIEvaluationOutput.model_validate(valid_payload())
    )

    assert records == []
