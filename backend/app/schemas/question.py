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
    full_solution: RequiredText

    @field_validator("rubric_points")
    @classmethod
    def validate_unique_rubric_points(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("评分点不能重复")
        return value


class QuestionResponse(QuestionInput):
    id: int
    created_at: datetime
    updated_at: datetime
