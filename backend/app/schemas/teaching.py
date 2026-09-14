from typing import Literal

from app.schemas.question import QuestionSchema

GeneratedTeachingAction = Literal[
    "ASK_FOCUSED_QUESTION",
    "GIVE_HINT",
    "GIVE_CORRECTION",
    "CORRECT_AND_ASK",
]


class TeachingSchema(QuestionSchema):
    pass
