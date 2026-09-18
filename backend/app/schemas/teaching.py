from typing import Literal

from pydantic import ConfigDict, Field

from app.schemas.ai_evaluation import AIEvaluationOutput
from app.schemas.question import QuestionSchema, RequiredText, to_camel_case

GeneratedTeachingAction = Literal[
    "ASK_FOCUSED_QUESTION",
    "GIVE_HINT",
    "GIVE_CORRECTION",
]


class TeachingSchema(QuestionSchema):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


class TeachingQuestion(TeachingSchema):
    id: RequiredText
    question: RequiredText


class TeachingOutput(TeachingSchema):
    content: RequiredText
    questions: list[TeachingQuestion] = Field(max_length=1)


class ReasonGuidanceExample(TeachingSchema):
    reason: RequiredText
    example: RequiredText


class InstructionFromRules(TeachingSchema):
    allowed_action: GeneratedTeachingAction
    do_not_repeat: list[RequiredText]
    do_not_reveal: list[RequiredText]
    response_goal: RequiredText


class TeachingContext(TeachingSchema):
    task_type: Literal["EXPLANATION_TEACHING"] = "EXPLANATION_TEACHING"
    question: dict[str, object]
    current_student_text: RequiredText
    latest_evaluation: AIEvaluationOutput
    teaching_history: list[dict[str, object]]
    instruction_from_rules: InstructionFromRules
    reason_guidance_examples: list[ReasonGuidanceExample] = Field(
        default_factory=list, alias="reasonGuidanceExamples"
    )
