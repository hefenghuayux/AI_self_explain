"""对话后核验的 AI 输出契约。

本模块只定义“问什么、AI 返回什么”。核验是否触发、问题数量上限之外的
状态转换、支持计数和最终状态由规则层决定，AI 输出不携带这些字段。
"""

from typing import Literal

from pydantic import ConfigDict, Field, StrictBool

from app.schemas.ai_evaluation import Reason
from app.schemas.question import QuestionSchema, RequiredText, to_camel_case

MasteryCheckReason = Reason
# 核验问题可以引用的证据来源，覆盖方案第 3 节列出的证据类型。
MasteryCheckEvidenceSource = Literal[
    "EVALUATION",
    "STUDENT_TEXT",
    "SUPPORT",
    "GUIDED_ANSWER",
    "RUBRIC_POINT",
    "QUESTION_CONDITION",
]
# 默认 1 个问题，只有存在两个相互独立、证据充分的未解决问题时才生成第 2 个。
MIN_MASTERY_CHECK_QUESTIONS = 1
MAX_MASTERY_CHECK_QUESTIONS = 2


class MasteryCheckEvidenceRef(QuestionSchema):
    model_config = ConfigDict(
        alias_generator=to_camel_case, populate_by_name=True, extra="forbid"
    )

    source: MasteryCheckEvidenceSource
    source_id: RequiredText
    quote: RequiredText


class MasteryCheckQuestion(QuestionSchema):
    model_config = ConfigDict(
        alias_generator=to_camel_case, populate_by_name=True, extra="forbid"
    )

    id: RequiredText
    question: RequiredText
    evidence_refs: list[MasteryCheckEvidenceRef] = Field(min_length=1)


class MasteryCheckQuestionsOutput(QuestionSchema):
    model_config = ConfigDict(
        alias_generator=to_camel_case, populate_by_name=True, extra="forbid"
    )

    questions: list[MasteryCheckQuestion]


class MasteryCheckAnswer(QuestionSchema):
    question_id: RequiredText
    answer: RequiredText


class MasteryCheckAnswerResult(QuestionSchema):
    model_config = ConfigDict(
        alias_generator=to_camel_case, populate_by_name=True, extra="forbid"
    )

    question_id: RequiredText
    passed: StrictBool
    basis: RequiredText


class MasteryCheckAssessmentOutput(QuestionSchema):
    model_config = ConfigDict(
        alias_generator=to_camel_case, populate_by_name=True, extra="forbid"
    )

    results: list[MasteryCheckAnswerResult]


def validate_question_count(question_count: int) -> list[str]:
    """校验核验问题数量。数量非法时返回明确错误，不做静默修正。"""
    if not MIN_MASTERY_CHECK_QUESTIONS <= question_count <= MAX_MASTERY_CHECK_QUESTIONS:
        return [
            f"核验问题数量必须在 {MIN_MASTERY_CHECK_QUESTIONS} 到 "
            f"{MAX_MASTERY_CHECK_QUESTIONS} 之间"
        ]
    return []


def validate_mastery_check_questions(output: MasteryCheckQuestionsOutput) -> list[str]:
    """校验 AI 生成的核验问题：数量、ID 唯一、证据引用齐全。"""
    errors = validate_question_count(len(output.questions))
    if errors:
        return errors
    question_ids = [question.id for question in output.questions]
    if len(question_ids) != len(set(question_ids)):
        return ["核验问题的 id 不能重复"]
    return []


def validate_mastery_check_assessment(
    output: MasteryCheckAssessmentOutput, question_ids: list[str]
) -> list[str]:
    """校验回答评价必须与已发送问题一一对应。"""
    expected_ids = set(question_ids)
    result_ids = [result.question_id for result in output.results]
    if set(result_ids) != expected_ids or len(result_ids) != len(expected_ids):
        return ["核验回答评价必须与已发送问题一一对应"]
    return []
