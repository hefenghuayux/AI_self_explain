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
    related_support_event_id: int | None
    request_id: str | None
    created_at: datetime


class ExternalCallRecordResponse(QuestionSchema):
    id: int
    call_type: str
    provider: str
    model: str
    attempt_number: int
    transport_status: str
    validation_status: str
    validation_errors: list[str] | None
    request_snapshot: dict[str, object] | None
    duration_ms: int
    error_type: str | None
    error_message: str | None
    raw_response: str | None
    request_id: str | None
    created_at: datetime


class TraceCorrelationResponse(QuestionSchema):
    session_id: int
    request_id: str | None = None


class TraceErrorResponse(QuestionSchema):
    type: str
    message: str


class TraceResultResponse(QuestionSchema):
    status: str
    duration_ms: int | None = None
    error: TraceErrorResponse | None = None


class TraceProducerResponse(QuestionSchema):
    service: str
    version: str


class TraceEventResponse(QuestionSchema):
    event_id: str
    sequence: int
    occurred_at: datetime
    event_name: str
    severity: str
    correlation: TraceCorrelationResponse
    operation: dict[str, object]
    result: TraceResultResponse
    data: dict[str, object]
    references: dict[str, object]
    privacy: dict[str, object] | None = None


class SessionTraceSummaryResponse(QuestionSchema):
    status: str
    flow_stage: str
    round: int
    event_count: int
    error_count: int
    external_call_count: int


class SessionTraceResponse(QuestionSchema):
    schema_version: str
    producer: TraceProducerResponse
    session_id: int
    generated_at: datetime
    summary: SessionTraceSummaryResponse
    events: list[TraceEventResponse]


class TraceExportEnvelope(QuestionSchema):
    schema_version: str
    producer: TraceProducerResponse
    session_id: int
    event: TraceEventResponse


class AuditExportResponse(QuestionSchema):
    session_id: int
    jsonl_path: str
    markdown_path: str
    event_count: int
