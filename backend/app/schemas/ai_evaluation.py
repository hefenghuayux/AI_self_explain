from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, StrictBool, field_validator, model_validator

from app.schemas.question import QuestionSchema, RequiredText, to_camel_case

Correctness = Literal["CORRECT", "WRONG"]
Completeness = Literal["COMPLETE", "INCOMPLETE"]
Reason = Literal[
    "表达与输入问题",
    "题意理解问题",
    "知识理解与回忆问题",
    "知识应用问题",
    "执行错误",
]


class ErrorEvidence(QuestionSchema):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )

    quote: RequiredText
    location_description: RequiredText
    reason: RequiredText
    thinking_direction: RequiredText


class AIEvaluationOutput(QuestionSchema):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )

    correctness: Correctness
    completeness: Completeness
    covered_points: list[int]
    error_evidence: list[ErrorEvidence]
    has_progress: StrictBool
    main_reason: Reason | None
    other_reasons: list[Reason] = Field(default_factory=list, max_length=1)
    judge_reason: RequiredText | None

    @model_validator(mode="before")
    @classmethod
    def discard_removed_fields(cls, value: object) -> object:
        if isinstance(value, dict):
            value = dict(value)
            value.pop("missingPoints", None)
            value.pop("confidence", None)
        return value


class AIEvaluationResponse(QuestionSchema):
    id: int
    correctness: Correctness
    completeness: Completeness
    covered_points: list[int]
    error_evidence: list[ErrorEvidence]
    prompt_version: str
    model_provider: str
    model_name: str
    created_at: datetime

    @field_validator("error_evidence", mode="before")
    @classmethod
    def parse_error_evidence(cls, value: object) -> object:
        if value is None:
            return []
        return [ErrorEvidence.model_validate(item) for item in value]


def evaluation_json_schema(rubric_points: list[str]) -> dict[str, object]:
    schema = AIEvaluationOutput.model_json_schema(by_alias=True)
    properties = schema["properties"]
    point_schema = {"type": "integer", "enum": list(range(1, len(rubric_points) + 1))}
    properties["coveredPoints"]["items"] = point_schema
    return schema


def validate_evaluation_relationships(
    evaluation: AIEvaluationOutput,
    rubric_points: list[str],
    confirmed_text: str,
) -> list[str]:
    errors: list[str] = []
    covered_points = set(evaluation.covered_points)
    expected_points = set(range(1, len(rubric_points) + 1))

    if len(covered_points) != len(evaluation.covered_points):
        errors.append("coveredPoints 不能包含重复评分点")
    if not covered_points <= expected_points:
        errors.append("coveredPoints 必须是题目评分点编号")
    for evidence in evaluation.error_evidence:
        if evidence.quote not in confirmed_text:
            errors.append("errorEvidence.quote 必须是 confirmedText 中的原文片段")
            break
    terminal = evaluation.correctness == "CORRECT" and evaluation.completeness == "COMPLETE"
    if terminal:
        if evaluation.main_reason is not None:
            errors.append("终态评价不能返回 mainReason")
        if evaluation.other_reasons:
            errors.append("终态评价不能返回 otherReasons")
        if evaluation.judge_reason is not None:
            errors.append("终态评价不能返回 judgeReason")
    else:
        if evaluation.main_reason is None:
            errors.append("非终态评价必须返回 mainReason")
        if evaluation.judge_reason is None:
            errors.append("非终态评价必须返回 judgeReason")
    if len(set(evaluation.other_reasons)) != len(evaluation.other_reasons):
        errors.append("otherReasons 不能包含重复原因")
    if evaluation.main_reason in evaluation.other_reasons:
        errors.append("otherReasons 不能包含 mainReason")
    return errors


def covered_point_labels(rubric_points: list[str], covered_points: list[int]) -> list[str]:
    return [rubric_points[index - 1] for index in covered_points]
