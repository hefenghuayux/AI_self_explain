from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
RequiredTextList = Annotated[list[RequiredText], Field(min_length=1)]
OptionalText = RequiredText | None
OptionalTextList = list[RequiredText] | None


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
    standard_answer: OptionalText = None
    rubric_points: OptionalTextList = None
    common_errors: OptionalTextList = None
    alternative_solutions: OptionalTextList = None
    layered_hints: OptionalTextList = None
    guided_questions: OptionalTextList = None
    full_solution: OptionalText = None

    @field_validator("standard_answer", "full_solution", mode="before")
    @classmethod
    def normalize_empty_text_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "rubric_points",
        "common_errors",
        "alternative_solutions",
        "layered_hints",
        "guided_questions",
        mode="before",
    )
    @classmethod
    def normalize_empty_list_to_none(cls, value: object) -> object:
        return None if value == [] else value

    @field_validator("rubric_points", "guided_questions")
    @classmethod
    def validate_unique_text_list(cls, value: list[str] | None, info) -> list[str] | None:
        if value is None:
            return value
        if len(set(value)) != len(value):
            label = "评分点" if info.field_name == "rubric_points" else "提示子问题"
            raise ValueError(f"{label}不能重复")
        return value


class QuestionResponse(QuestionSchema):
    id: int
    question_content: RequiredText
    standard_answer: str | None
    rubric_points: list[str] | None
    common_errors: list[str] | None
    alternative_solutions: list[str] | None
    layered_hints: list[str] | None
    guided_questions: list[str] | None
    full_solution: str | None
    tiku_question_id: int | None = None
    grade_period: int | None = None
    subject: str | None = None
    q_type: int | None = None
    difficulty_level: int | None = None
    review: str | None = None
    topics: str | None = None
    method: str | None = None
    evaluation_mode: str
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
