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


class AIEvaluationOutput(QuestionSchema):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )

    correctness: Correctness
    completeness: Completeness
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
            value.pop("coveredPoints", None)
            value.pop("errorEvidence", None)
        return value


class AIEvaluationResponse(QuestionSchema):
    id: int
    correctness: Correctness
    completeness: Completeness
    prompt_version: str
    model_provider: str
    model_name: str
    created_at: datetime


def evaluation_json_schema(rubric_points: list[str]) -> dict[str, object]:
    return AIEvaluationOutput.model_json_schema(by_alias=True)


def validate_evaluation_relationships(
    evaluation: AIEvaluationOutput,
) -> list[str]:
    errors: list[str] = []
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
