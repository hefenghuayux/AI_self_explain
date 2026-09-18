import logging
from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, StrictBool, model_validator

from app.schemas.question import QuestionSchema, RequiredText, to_camel_case

logger = logging.getLogger(__name__)
# 迁移期间仍被静默丢弃的旧字段。所有模型请求和历史重放迁移完成后，
# 应删除这份兼容逻辑并让 extra="forbid" 直接拒绝旧契约。
LEGACY_EVALUATION_FIELDS = ("missingPoints", "confidence", "coveredPoints", "errorEvidence")

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
            discarded = []
            for field in LEGACY_EVALUATION_FIELDS:
                if field in value:
                    value.pop(field)
                    discarded.append(field)
            if discarded:
                logger.warning(
                    "AI 评价输出包含已废弃字段，已忽略：%s",
                    "、".join(discarded),
                    extra={
                        "eventName": "ai.output.legacy_fields_discarded",
                        "legacyFields": ",".join(discarded),
                    },
                )
        return value


class AIEvaluationResponse(QuestionSchema):
    id: int
    correctness: Correctness
    completeness: Completeness
    prompt_version: str
    model_provider: str
    model_name: str
    created_at: datetime


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
