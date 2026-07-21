from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.ai_evaluation import AIEvaluationResponse, Completeness, Correctness, NextAction
from app.schemas.question import QuestionSchema, RequiredText
from app.schemas.support import GuidedAnswer, SupportEventResponse

SessionStatus = Literal["IN_PROGRESS", "COMPLETED", "STOPPED_LIMIT", "NEED_HUMAN", "PAUSED"]
FlowStage = Literal[
    "WAIT_INITIAL_CHOICE",
    "CAPTURING_INPUT",
    "TRANSCRIBING",
    "CONFIRMING_TEXT",
    "AI_EVALUATING",
    "WAIT_STUDENT_ACTION",
    "WAIT_GUIDED_ANSWERS",
    "SHOWING_FULL_SOLUTION",
]
InitialChoice = Literal["KNOW", "NOT_KNOW", "HAS_QUESTION"]


class CreateSessionInput(QuestionSchema):
    question_id: int = Field(gt=0)


class InitialChoiceInput(QuestionSchema):
    choice: InitialChoice
    version: int = Field(ge=0)


class TextAttemptInput(QuestionSchema):
    confirmed_text: RequiredText
    version: int = Field(ge=0)


class VoiceTranscriptConfirmationInput(TextAttemptInput):
    attempt_id: int = Field(gt=0)


class PendingVoiceAttemptResponse(QuestionSchema):
    id: int
    audio_file_id: int
    asr_transcript: str


class EvaluationRetryInput(QuestionSchema):
    version: int = Field(ge=0)


class StudentActionInput(QuestionSchema):
    version: int = Field(ge=0)


class HelpRequestInput(StudentActionInput):
    main_draft: str = ""


class DoubtRequestInput(HelpRequestInput):
    doubt_text: RequiredText


class GuidedAnswersInput(StudentActionInput):
    answers: list[GuidedAnswer] = Field(min_length=1)


class AppealInput(StudentActionInput):
    reason: RequiredText


class SolutionUnderstandingInput(StudentActionInput):
    understood: bool


TimelineEventType = Literal["EVALUATION", "SUPPORT", "FULL_SOLUTION", "NEED_HUMAN"]
TimelineSupportType = Literal[
    "ASK_FOCUSED_QUESTION",
    "GIVE_HINT",
    "GIVE_CORRECTION",
    "CORRECT_AND_ASK",
]


class LearningTimelineItemResponse(QuestionSchema):
    id: str
    event_type: TimelineEventType
    content: str
    correctness: Correctness | None
    completeness: Completeness | None
    action: NextAction | TimelineSupportType | None
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
    pending_voice_attempt: PendingVoiceAttemptResponse | None = None
