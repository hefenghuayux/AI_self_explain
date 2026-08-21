from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.schemas.question import to_camel_case
from app.schemas.session_event import EventType


class ProjectionSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        frozen=True,
    )


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


class Trajectory(ProjectionSchema):
    session_id: int
    runs: tuple[TrajectoryRun, ...]


class TraceNode(ProjectionSchema):
    seq: int
    event_type: EventType
    children: tuple["TraceNode", ...]


class Trace(ProjectionSchema):
    session_id: int
    run_id: str
    roots: tuple[TraceNode, ...]
