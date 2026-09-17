from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_serializer

from app.schemas.question import to_camel_case
from app.schemas.session_event import EventType


class ProjectionSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        frozen=True,
    )

    @field_serializer("occurred_at", "started_at", check_fields=False)
    def _serialize_utc(self, value: datetime) -> str:
        """SQLite 读回的时间会丢失时区，必须显式补成带 Z 的 UTC。

        否则 API 输出无时区标记的时间串，前端 new Date() 会按本地时间解析，
        把 UTC 值当成本地时间，显示结果整体偏移一个时区。
        """
        moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


class SurfaceMessage(ProjectionSchema):
    seq: int
    role: Literal["user"]
    content: str


class SurfaceContext(ProjectionSchema):
    seq: int
    kind: Literal["question", "rubric", "session_state", "memory"]
    source: str
    content: str | dict[str, JsonValue]


class Surface(ProjectionSchema):
    session_id: int
    as_of_seq: int
    messages: tuple[SurfaceMessage, ...]
    contexts: tuple[SurfaceContext, ...]


class UserInputStep(ProjectionSchema):
    kind: Literal["user_input"] = "user_input"
    event_seq: int
    summary: str


class ModelCallStep(ProjectionSchema):
    kind: Literal["model_call"] = "model_call"
    request_seq: int
    result_seq: int | None = None
    status: Literal["pending", "success", "failed"]
    duration_ms: int | None = None


class StateChangeStep(ProjectionSchema):
    kind: Literal["state_change"] = "state_change"
    event_seq: int
    from_: str = Field(alias="from")
    to: str


TrajectoryStep = Annotated[
    UserInputStep | ModelCallStep | StateChangeStep,
    Field(discriminator="kind"),
]


class TrajectoryRun(ProjectionSchema):
    run_id: str
    started_at: datetime
    steps: tuple[TrajectoryStep, ...]
    records: tuple["TrajectoryRecord", ...]


class Trajectory(ProjectionSchema):
    session_id: int
    runs: tuple[TrajectoryRun, ...]
    events: tuple["TrajectoryRecord", ...]


TrajectoryRecordKind = Literal[
    "session",
    "user",
    "context",
    "model_request",
    "model_response",
    "model_error",
    "state_change",
]

TrajectoryRecordStatus = Literal["complete", "pending", "failed"]


class SessionRecordDetail(ProjectionSchema):
    pass


class UserRecordDetail(ProjectionSchema):
    text: str
    input_type: Literal["text", "voice"] = Field(alias="inputType")


class ContextRecordDetail(ProjectionSchema):
    kind: Literal["question", "rubric", "session_state", "memory"]
    source: str
    content: str | dict[str, JsonValue]


class ModelRequestDetail(ProjectionSchema):
    provider: str
    model: str
    messages: tuple[dict[str, JsonValue], ...]
    surface_seq: int = Field(alias="surfaceSeq")


class ModelResponseDetail(ProjectionSchema):
    output: dict[str, JsonValue]
    # rawContent 是 commit 46e3466 才加入的展示字段，更早写入的历史事件没有它。
    raw_content: str | None = Field(default=None, alias="rawContent")
    validation: Literal["valid", "invalid"]
    input_tokens: int | None = Field(default=None, alias="inputTokens")
    output_tokens: int | None = Field(default=None, alias="outputTokens")
    prompt_cache_hit_tokens: int | None = Field(default=None, alias="promptCacheHitTokens")
    prompt_cache_miss_tokens: int | None = Field(default=None, alias="promptCacheMissTokens")


class ModelErrorDetail(ProjectionSchema):
    error_type: str = Field(alias="errorType")
    message: str


class StateChangeDetail(ProjectionSchema):
    from_: str = Field(alias="from")
    to: str
    reason: str


class TrajectoryRecordDetail(ProjectionSchema):
    session: SessionRecordDetail | None = None
    user: UserRecordDetail | None = None
    context: ContextRecordDetail | None = None
    model_request: ModelRequestDetail | None = Field(default=None, alias="modelRequest")
    model_response: ModelResponseDetail | None = Field(default=None, alias="modelResponse")
    model_error: ModelErrorDetail | None = Field(default=None, alias="modelError")
    state_change: StateChangeDetail | None = Field(default=None, alias="stateChange")


class TrajectoryRecord(ProjectionSchema):
    index: int
    event_seq: int
    event_id: str
    event_type: EventType
    kind: TrajectoryRecordKind
    label: str
    # summary 是账本收起时的单行预览，可能被截断；full_text 是未压缩的完整原文。
    summary: str
    full_text: str
    status: TrajectoryRecordStatus = "complete"
    duration_ms: int | None = None
    occurred_at: datetime
    parent_event_id: str | None = None
    detail: TrajectoryRecordDetail


class TraceNode(ProjectionSchema):
    seq: int
    event_type: EventType
    children: tuple["TraceNode", ...]


class Trace(ProjectionSchema):
    session_id: int
    run_id: str
    roots: tuple[TraceNode, ...]
