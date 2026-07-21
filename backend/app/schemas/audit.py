from datetime import datetime

from app.schemas.question import QuestionSchema


class StateTransitionEventResponse(QuestionSchema):
    id: int
    trigger_type: str
    from_status: str
    to_status: str
    from_flow_stage: str | None
    to_flow_stage: str
    before_snapshot: dict[str, object]
    after_snapshot: dict[str, object]
    related_attempt_id: int | None
    related_evaluation_id: int | None
    request_id: str | None
    created_at: datetime


class ExternalCallRecordResponse(QuestionSchema):
    id: int
    call_type: str
    provider: str
    model: str
    attempt_number: int
    status: str
    duration_ms: int
    error_type: str | None
    error_message: str | None
    raw_response: str | None
    request_id: str | None
    created_at: datetime
