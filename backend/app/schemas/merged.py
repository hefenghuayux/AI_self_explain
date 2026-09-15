from typing import Literal

from pydantic import ConfigDict, Field, StrictBool, model_validator

from app.schemas.ai_evaluation import (
    AIEvaluationOutput,
    Completeness,
    Correctness,
    ErrorEvidence,
    validate_evaluation_relationships,
)
from app.schemas.question import QuestionSchema, RequiredText, to_camel_case

MergedTeachingAction = Literal[
    "ASK_FOCUSED_QUESTION",
    "GIVE_HINT",
    "GIVE_CORRECTION",
    "CORRECT_AND_ASK",
]
Reason = Literal[
    "表达与输入问题",
    "题意理解问题",
    "知识理解与回忆问题",
    "知识应用问题",
    "执行错误",
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

    teachingAction 由大模型根据学生原文和历史判断的 hasProgress 选择：
    - 有进展且不完整 → 追问（ASK_FOCUSED_QUESTION / CORRECT_AND_ASK）
    - 无进展 → 提示（GIVE_HINT），不以新增评分点作为判断依据
    - 有错误 → 纠错（GIVE_CORRECTION）
    correctness = CORRECT + COMPLETE 时，原因、teachingAction、content、questions 均应为空。
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
    has_progress: StrictBool
    main_reason: Reason | None
    other_reasons: list[Reason] = Field(default_factory=list)
    judge_reason: RequiredText | None
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
    if not terminal:
        if output.teaching_action is None:
            errors.append("非终态评价必须返回 teachingAction")
        if output.main_reason is None:
            errors.append("非终态评价必须返回具体 main_reason")
        if output.judge_reason is None:
            errors.append("非终态评价必须返回 judge_reason")
    if terminal and output.main_reason is not None:
        errors.append("终态评价不能返回 main_reason")
    if terminal and output.other_reasons:
        errors.append("终态评价不能返回 other_reasons")
    if terminal and output.judge_reason is not None:
        errors.append("终态评价不能返回 judge_reason")
    if terminal and output.teaching_action is not None:
        errors.append("终态评价不能返回 teachingAction")
    if terminal and output.content is not None:
        errors.append("终态评价不能返回教学 content")
    if terminal and output.questions:
        errors.append("终态评价不能返回教学 questions")
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
    )
