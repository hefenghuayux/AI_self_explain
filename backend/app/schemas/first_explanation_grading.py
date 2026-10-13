from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, StrictInt, StrictStr

from app.schemas.question import QuestionSchema
from app.schemas.session import SessionResponse

GradingStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED"]


class AmbiguityNote(QuestionSchema):
    model_config = ConfigDict(extra="forbid")
    source: StrictStr
    interpretation: StrictStr
    impact: StrictStr


class FirstExplanationGradingOutput(QuestionSchema):
    model_config = ConfigDict(extra="forbid")
    correctness_score: StrictInt = Field(ge=0, le=4)
    correctness_reason: StrictStr
    completeness_score: StrictInt = Field(ge=0, le=4)
    completeness_reason: StrictStr
    missing_requirements: list[StrictStr]
    ambiguity_notes: list[AmbiguityNote]
    rubric_limitations: list[StrictStr]
    summary: StrictStr


class FirstExplanationGradingReport(FirstExplanationGradingOutput):
    total_score: float = Field(ge=0, le=100)


class FirstExplanationGradingResponse(QuestionSchema):
    id: int
    attempt_id: int
    status: GradingStatus
    evaluation_status: GradingStatus
    report: FirstExplanationGradingReport | None
    evaluation_error: str | None
    error_message: str | None
    acknowledged_at: datetime | None
    standard_version: str
    created_at: datetime


class FirstExplanationSubmissionResponse(QuestionSchema):
    session: SessionResponse
    grading: FirstExplanationGradingResponse
