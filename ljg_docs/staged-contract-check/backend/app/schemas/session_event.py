from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.schemas.question import QuestionSchema

EventType: TypeAlias = Literal[
    "session.started",
    "user.message",
    "context.added",
    "model.requested",
    "model.responded",
    "model.failed",
    "state.changed",
]
NonEmptyText = Annotated[str, Field(min_length=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class EventData(BaseModel):
    model_config = ConfigDict(extra="forbid", alias_generator=None)


class SessionStartedData(EventData):
    pass


class UserMessageData(EventData):
    text: NonEmptyText
    inputType: Literal["text", "voice"]


class ContextAddedData(EventData):
    kind: Literal["question", "rubric", "session_state", "memory"]
    source: NonEmptyText
    content: NonEmptyText | dict[str, JsonValue]


class ModelMessage(EventData):
    role: NonEmptyText
    content: NonEmptyText


class ModelRequestedData(EventData):
    provider: NonEmptyText
    model: NonEmptyText
    messages: Annotated[list[ModelMessage], Field(min_length=1)]
    surfaceSeq: NonNegativeInt


class ModelRespondedData(EventData):
    output: dict[str, JsonValue]
    rawContent: NonEmptyText
    validation: Literal["valid", "invalid"]
    durationMs: NonNegativeInt | None = None
    inputTokens: NonNegativeInt | None = None
    outputTokens: NonNegativeInt | None = None


class ModelFailedData(EventData):
    errorType: Literal["TIMEOUT", "CONNECTION_ERROR", "HTTP_ERROR", "INVALID_RESPONSE", "UNKNOWN"]
    message: NonEmptyText
    durationMs: NonNegativeInt | None = None


class StateChangedData(EventData):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: NonEmptyText = Field(alias="from")
    to: NonEmptyText
    reason: NonEmptyText


EVENT_DATA_SCHEMAS: dict[str, type[EventData]] = {
    "session.started": SessionStartedData,
    "user.message": UserMessageData,
    "context.added": ContextAddedData,
    "model.requested": ModelRequestedData,
    "model.responded": ModelRespondedData,
    "model.failed": ModelFailedData,
    "state.changed": StateChangedData,
}


class SessionEventResponse(QuestionSchema):
    session_id: int
    seq: int
    event_id: str
    run_id: str | None = None
    parent_event_id: str | None = None
    event_type: EventType
    occurred_at: datetime
    data: dict[str, JsonValue]


class SessionEventListResponse(QuestionSchema):
    session_id: int
    events: list[SessionEventResponse]
    next_after_seq: int
