from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
RequiredTextList = Annotated[list[RequiredText], Field(min_length=1)]


def to_camel_case(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(item.capitalize() for item in tail)


class QuestionSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        from_attributes=True,
    )


class QuestionInput(QuestionSchema):
    question_content: RequiredText
    standard_answer: RequiredText
    rubric_points: RequiredTextList
    common_errors: RequiredTextList
    alternative_solutions: RequiredTextList
    layered_hints: RequiredTextList
    guided_questions: RequiredTextList
    full_solution: RequiredText

    @field_validator("rubric_points", "guided_questions")
    @classmethod
    def validate_unique_text_list(cls, value: list[str], info) -> list[str]:
        if len(set(value)) != len(value):
            label = "评分点" if info.field_name == "rubric_points" else "提示子问题"
            raise ValueError(f"{label}不能重复")
        return value


class QuestionResponse(QuestionInput):
    # 阶段 07 迁移后的历史题目允许为空，后续编辑仍由 QuestionInput 强制补录。
    guided_questions: list[RequiredText]
    id: int
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
