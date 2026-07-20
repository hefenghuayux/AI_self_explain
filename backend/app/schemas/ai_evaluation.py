from datetime import datetime
from typing import Literal

from pydantic import ConfigDict

from app.schemas.question import QuestionSchema, RequiredText, to_camel_case

Correctness = Literal["CORRECT", "WRONG", "UNCERTAIN"]
Completeness = Literal["COMPLETE", "INCOMPLETE"]
NextAction = Literal[
    "COMPLETE",
    "ASK_FOCUSED_QUESTION",
    "GIVE_CORRECTION",
    "CORRECT_AND_ASK",
    "GIVE_HINT",
    "NEED_HUMAN",
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
    covered_points: list[RequiredText]
    missing_points: list[RequiredText]
    error_evidence: list[ErrorEvidence]
    feedback: RequiredText
    confidence: Literal[1]
    next_action: NextAction
    need_human_reason: RequiredText | None


class AIEvaluationResponse(QuestionSchema):
    id: int
    correctness: Correctness
    completeness: Completeness
    covered_points: list[str]
    missing_points: list[str]
    error_evidence: list[ErrorEvidence]
    feedback: str
    confidence: float
    next_action: NextAction
    need_human_reason: str | None
    prompt_version: str
    model_provider: str
    model_name: str
    created_at: datetime


def evaluation_json_schema(rubric_points: list[str]) -> dict[str, object]:
    schema = AIEvaluationOutput.model_json_schema(by_alias=True)
    properties = schema["properties"]
    point_schema = {"type": "string", "enum": rubric_points}
    properties["coveredPoints"]["items"] = point_schema
    properties["missingPoints"]["items"] = point_schema
    return schema


def validate_evaluation_relationships(
    evaluation: AIEvaluationOutput,
    rubric_points: list[str],
    confirmed_text: str,
) -> list[str]:
    errors: list[str] = []
    covered_points = set(evaluation.covered_points)
    missing_points = set(evaluation.missing_points)
    expected_points = set(rubric_points)

    if len(covered_points) != len(evaluation.covered_points):
        errors.append("coveredPoints 不能包含重复评分点")
    if len(missing_points) != len(evaluation.missing_points):
        errors.append("missingPoints 不能包含重复评分点")
    if covered_points & missing_points:
        errors.append("coveredPoints 与 missingPoints 不能重叠")
    if covered_points | missing_points != expected_points:
        errors.append("coveredPoints 与 missingPoints 必须完整覆盖题目评分点")

    if evaluation.next_action == "NEED_HUMAN":
        if evaluation.need_human_reason is None:
            errors.append("nextAction 为 NEED_HUMAN 时 needHumanReason 必填")
    elif evaluation.need_human_reason is not None:
        errors.append("nextAction 不是 NEED_HUMAN 时 needHumanReason 必须为空")

    required_actions = {
        ("CORRECT", "COMPLETE"): "COMPLETE",
        ("CORRECT", "INCOMPLETE"): "ASK_FOCUSED_QUESTION",
        ("WRONG", "COMPLETE"): "GIVE_CORRECTION",
        ("WRONG", "INCOMPLETE"): "CORRECT_AND_ASK",
        ("UNCERTAIN", "COMPLETE"): "NEED_HUMAN",
        ("UNCERTAIN", "INCOMPLETE"): "NEED_HUMAN",
    }
    required_action = required_actions[(evaluation.correctness, evaluation.completeness)]
    if evaluation.next_action != "NEED_HUMAN" and evaluation.next_action != required_action:
        errors.append(
            "correctness、completeness 与 nextAction 组合不符合评价状态转换表"
        )
    if evaluation.correctness == "UNCERTAIN" and evaluation.next_action != "NEED_HUMAN":
        errors.append("correctness 为 UNCERTAIN 时 nextAction 必须为 NEED_HUMAN")

    for evidence in evaluation.error_evidence:
        if evidence.quote not in confirmed_text:
            errors.append("errorEvidence.quote 必须是 confirmedText 中的原文片段")
            break
    return errors
