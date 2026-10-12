from datetime import datetime

from pydantic import Field

from app.schemas.question import QuestionSchema


class StepResponse(QuestionSchema):
    id: int
    step_content: str | None
    explain_transcript: str | None
    updated_at: datetime


class StepsResponse(QuestionSchema):
    round: int
    current_step_id: int | None
    version: int
    step: StepResponse | None


class StepAttemptInput(QuestionSchema):
    current_step_content: str = Field(default="", max_length=4000)
    version: int = Field(ge=0)
