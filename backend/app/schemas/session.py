from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.question import QuestionSchema, RequiredText

SessionStatus = Literal["IN_PROGRESS", "COMPLETED", "STOPPED_LIMIT", "NEED_HUMAN", "PAUSED"]
FlowStage = Literal[
    "WAIT_INITIAL_CHOICE",
    "CAPTURING_INPUT",
    "TRANSCRIBING",
    "CONFIRMING_TEXT",
    "AI_EVALUATING",
    "WAIT_STUDENT_ACTION",
    "SHOWING_FULL_SOLUTION",
]
InitialChoice = Literal["KNOW", "NOT_KNOW"]


class CreateSessionInput(QuestionSchema):
    question_id: int = Field(gt=0)


class InitialChoiceInput(QuestionSchema):
    choice: InitialChoice
    version: int = Field(ge=0)


class TextAttemptInput(QuestionSchema):
    confirmed_text: RequiredText
    version: int = Field(ge=0)


class SessionResponse(QuestionSchema):
    id: int
    question_id: int
    initial_choice: InitialChoice | None
    status: SessionStatus
    flow_stage: FlowStage
    round: int
    support_count_round: int
    support_count_total: int
    no_progress_count: int
    solution_exposed: bool
    completion_type: str | None
    need_human_reason: str | None
    covered_points_current_round: list[str]
    covered_points_all: list[str]
    paused_from_stage: FlowStage | None
    version: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
