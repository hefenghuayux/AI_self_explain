from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.ai_evaluation import AIEvaluationResponse, Completeness, Correctness
from app.schemas.question import QuestionSchema, RequiredText
from app.schemas.support import GuidedAnswer, SupportEventResponse

SessionStatus = Literal["IN_PROGRESS", "COMPLETED", "STOPPED_LIMIT", "NEED_HUMAN", "PAUSED"]
FlowStage = Literal[
    "WAIT_INITIAL_CHOICE",
    "CAPTURING_INPUT",
    "TRANSCRIBING",
    "AI_EVALUATING",
    "WAIT_STUDENT_ACTION",
    "WAIT_GUIDED_ANSWERS",
    "SHOWING_FULL_SOLUTION",
]
InitialChoice = Literal["KNOW", "NOT_KNOW", "HAS_QUESTION"]
VoiceInputTarget = Literal["SELF_EXPLANATION", "GUIDED_ANSWER", "DOUBT", "APPEAL"]


class CreateSessionInput(QuestionSchema):
    question_id: int = Field(gt=0)


class InitialChoiceInput(QuestionSchema):
    choice: InitialChoice
    version: int = Field(ge=0)


class TextAttemptInput(QuestionSchema):
    confirmed_text: RequiredText = Field(max_length=4000)
    version: int = Field(ge=0)
    voice_attempt_id: int | None = Field(default=None, gt=0)


class StudentActionInput(QuestionSchema):
    version: int = Field(ge=0)


class HelpRequestInput(StudentActionInput):
    main_draft: str = ""


class DoubtRequestInput(HelpRequestInput):
    doubt_text: RequiredText
    voice_attempt_id: int | None = Field(default=None, gt=0)


class GuidedAnswersInput(StudentActionInput):
    answers: list[GuidedAnswer] = Field(min_length=1)
    voice_attempt_id: int | None = Field(default=None, gt=0)


class AppealInput(StudentActionInput):
    reason: RequiredText
    voice_attempt_id: int | None = Field(default=None, gt=0)


class SolutionUnderstandingInput(StudentActionInput):
    understood: bool


TimelineEventType = Literal[
    "SUBMISSION",
    "EVALUATION",
    "SUPPORT",
    "FULL_SOLUTION",
    "NEED_HUMAN",
]
TimelineSpeaker = Literal["STUDENT", "AI", "SYSTEM"]
TimelineSubmissionType = Literal[
    "SELF_EXPLANATION",
    "SUPPORT_REQUEST",
    "GUIDED_ANSWER",
    "DOUBT",
    "APPEAL",
]
TimelineSupportType = Literal[
    "ASK_FOCUSED_QUESTION",
    "GIVE_HINT",
    "GIVE_CORRECTION",
    "CORRECT_AND_ASK",
]
TimelineAction = Literal["COMPLETE", "NEED_HUMAN"] | TimelineSupportType


class LearningTimelineItemResponse(QuestionSchema):
    id: str
    event_type: TimelineEventType
    speaker: TimelineSpeaker
    submission_type: TimelineSubmissionType | None
    content: str
    correctness: Correctness | None
    completeness: Completeness | None
    action: TimelineAction | None
    created_at: datetime


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
    no_progress_help_request_count: int
    solution_exposed: bool
    completion_type: str | None
    need_human_reason: str | None
    covered_points_current_round: list[str]
    covered_points_all: list[str]
    current_draft: str
    paused_from_stage: FlowStage | None
    version: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    latest_evaluation: AIEvaluationResponse | None = None
    latest_support: SupportEventResponse | None = None
