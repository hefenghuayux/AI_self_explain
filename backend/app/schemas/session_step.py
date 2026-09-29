from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.question import QuestionSchema

StepStatus = Literal["DRAFT", "SAVED", "SUBMITTED"]


class StepResponse(QuestionSchema):
    id: int
    seq: int
    step_content: str | None
    explain_transcript: str | None
    status: StepStatus
    updated_at: datetime


class StepsResponse(QuestionSchema):
    round: int
    draft_id: str
    current_step_id: int | None
    version: int
    steps: list[StepResponse]


class StepNextInput(QuestionSchema):
    step_content: str = Field(default="", max_length=4000)
    version: int = Field(ge=0)


class StepActivateInput(QuestionSchema):
    current_step_id: int = Field(gt=0)
    current_step_content: str = Field(default="", max_length=4000)
    version: int = Field(ge=0)


class StepAttemptInput(QuestionSchema):
    current_step_id: int = Field(gt=0)
    current_step_content: str = Field(default="", max_length=4000)
    version: int = Field(ge=0)
