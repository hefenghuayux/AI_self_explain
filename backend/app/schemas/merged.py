from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.schemas.ai_evaluation import (
    AIEvaluationOutput,
    Completeness,
    Correctness,
    ErrorEvidence,
    validate_evaluation_relationships,
)
from app.schemas.question import QuestionSchema, RequiredText, to_camel_case
from app.schemas.teaching import GeneratedTeachingAction

MergedTeachingAction = Literal[
    "ASK_FOCUSED_QUESTION",
    "GIVE_HINT",
    "GIVE_CORRECTION",
    "CORRECT_AND_ASK",
]


class MergedTeachingQuestion(QuestionSchema):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )

    id: RequiredText = Field(max_length=100)
    question: RequiredText = Field(max_length=180)


class MergedModelOutput(QuestionSchema):
    """评价 + 教学一次调用的合并输出。

    teachingAction 由大模型根据“是否有新增评分点”等上下文自行判断：
    - 有新评分点且不完整 → 追问（ASK_FOCUSED_QUESTION / CORRECT_AND_ASK）
    - 无新评分点 → 提示（GIVE_HINT）
    - 有错误 → 纠错（GIVE_CORRECTION）
    correctness = CORRECT + COMPLETE，或 UNCERTAIN 时，
    teachingAction / content / questions 均应为空。
    """

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
    need_human_reason: RequiredText | None
    teaching_action: MergedTeachingAction | None = None
    content: str | None = None
    questions: list[MergedTeachingQuestion] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_removed_fields(cls, value: object) -> object:
        if isinstance(value, dict):
            value = dict(value)
            value.pop("missingPoints", None)
            value.pop("confidence", None)
        return value


def merged_json_schema(rubric_points: list[str]) -> dict[str, object]:
    schema = MergedModelOutput.model_json_schema(by_alias=True)
    properties = schema["properties"]
    point_schema = {"type": "integer", "enum": list(range(1, len(rubric_points) + 1))}
    properties["coveredPoints"]["items"] = point_schema
    return schema


def validate_merged_output(
    output: MergedModelOutput,
    rubric_points: list[str],
    confirmed_text: str,
) -> list[str]:
    errors = list(
        validate_evaluation_relationships(
            _as_evaluation_output(output),
            rubric_points,
            confirmed_text,
        )
    )
    terminal = output.correctness == "CORRECT" and output.completeness == "COMPLETE"
    uncertain = output.correctness == "UNCERTAIN"
    if (terminal or uncertain) and output.teaching_action is not None:
        errors.append("终态或不确定评价不能返回 teachingAction")
    if (terminal or uncertain) and output.content is not None:
        errors.append("终态或不确定评价不能返回教学 content")
    if (terminal or uncertain) and output.questions:
        errors.append("终态或不确定评价不能返回教学 questions")
    if output.teaching_action in {"ASK_FOCUSED_QUESTION", "CORRECT_AND_ASK"}:
        if len(output.questions) != 1:
            errors.append("追问或纠错后追问必须恰好返回一个子问题")
    elif output.questions:
        errors.append("非追问动作不能返回子问题")
    return errors


def _as_evaluation_output(output: MergedModelOutput) -> AIEvaluationOutput:
    return AIEvaluationOutput(
        correctness=output.correctness,
        completeness=output.completeness,
        covered_points=output.covered_points,
        error_evidence=output.error_evidence,
        need_human_reason=output.need_human_reason,
    )