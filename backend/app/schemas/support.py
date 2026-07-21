from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, field_validator

from app.schemas.question import QuestionSchema, RequiredText, to_camel_case

SupportType = Literal["ASK_FOCUSED_QUESTION", "GIVE_HINT", "GIVE_CORRECTION", "CORRECT_AND_ASK"]
SupportKind = Literal["EVALUATION", "GUIDED_QUESTIONS", "SIMPLE_DOUBT", "CURRENT_STEP"]
SupportAction = Literal[
    "GUIDED_QUESTIONS",
    "SIMPLE_DOUBT_ANSWER",
    "REFUSE_FULL_SOLUTION",
    "CURRENT_STEP_ANSWER",
]


class SupportContentOutput(QuestionSchema):
    content: RequiredText


class GuidedQuestion(QuestionSchema):
    id: RequiredText
    question: RequiredText


class SupportRequestOutput(QuestionSchema):
    model_config = ConfigDict(
        alias_generator=to_camel_case, populate_by_name=True, extra="forbid"
    )

    action: SupportAction
    covered_points: list[RequiredText]
    missing_points: list[RequiredText]
    content: RequiredText
    questions: list[GuidedQuestion]


class GuidedAnswer(QuestionSchema):
    question_id: RequiredText
    answer: RequiredText


class GuidedAnswerResult(QuestionSchema):
    question_id: RequiredText
    result: Literal["CORRECT", "INCORRECT", "INCOMPLETE"]


class GuidedAnswerAssessmentOutput(QuestionSchema):
    model_config = ConfigDict(
        alias_generator=to_camel_case, populate_by_name=True, extra="forbid"
    )

    results: list[GuidedAnswerResult]
    content: RequiredText


class SupportEventResponse(QuestionSchema):
    id: int
    support_type: SupportType
    round: int
    status: Literal["VALID", "REFUSED"]
    content: str
    support_kind: SupportKind
    main_draft: str | None
    doubt_text: str | None
    guided_questions: list[GuidedQuestion] | None
    guided_answers: list[GuidedAnswer] | None
    follow_up_content: str | None
    created_at: datetime

    @field_validator("guided_questions", mode="before")
    @classmethod
    def parse_guided_questions(cls, value: object) -> object:
        if value is None:
            return None
        return [GuidedQuestion.model_validate(item) for item in value]

    @field_validator("guided_answers", mode="before")
    @classmethod
    def parse_guided_answers(cls, value: object) -> object:
        if value is None:
            return None
        return [GuidedAnswer.model_validate(item) for item in value]
