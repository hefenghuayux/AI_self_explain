from datetime import datetime
from typing import Literal

from app.schemas.question import QuestionSchema, RequiredText

SupportType = Literal["GIVE_HINT", "GIVE_CORRECTION", "CORRECT_AND_ASK"]


class SupportContentOutput(QuestionSchema):
    content: RequiredText


class SupportEventResponse(QuestionSchema):
    id: int
    support_type: SupportType
    round: int
    status: Literal["VALID"]
    content: str
    created_at: datetime
