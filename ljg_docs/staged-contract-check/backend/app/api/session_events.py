from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import DatabaseSession, require_teacher
from app.schemas.session_event import SessionEventListResponse, SessionEventResponse
from app.schemas.session_projection import Surface, Trace, Trajectory
from app.services.event_store import EventNotFoundError, EventStore, SessionNotFoundError
from app.services.surface import SurfaceService
from app.services.trace import TraceService
from app.services.trajectory import TrajectoryService

router = APIRouter(
    prefix="/sessions",
    tags=["session-events"],
    dependencies=[Depends(require_teacher)],
)


def _session_not_found(error: SessionNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SESSION_NOT_FOUND")


@router.get("/{session_id}/events", response_model=SessionEventListResponse)
def list_session_events(
    session_id: int,
    database_session: DatabaseSession,
    after_seq: int = Query(default=-1, alias="afterSeq", ge=-1),
    limit: int = Query(default=100, ge=1, le=500),
) -> SessionEventListResponse:
    try:
        events = EventStore(database_session).list_events(
            session_id, after_seq=after_seq, limit=limit
        )
    except SessionNotFoundError as error:
        raise _session_not_found(error) from error
    return SessionEventListResponse(
        session_id=session_id,
        events=[SessionEventResponse.model_validate(event) for event in events],
        next_after_seq=events[-1].seq if events else after_seq,
    )


@router.get("/{session_id}/events/{seq}", response_model=SessionEventResponse)
def get_session_event(
    session_id: int, seq: int, database_session: DatabaseSession
) -> SessionEventResponse:
    try:
        event = EventStore(database_session).get_event(session_id, seq)
    except SessionNotFoundError as error:
        raise _session_not_found(error) from error
    except EventNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="EVENT_NOT_FOUND"
        ) from error
    return SessionEventResponse.model_validate(event)


@router.get("/{session_id}/surface", response_model=Surface)
def get_session_surface(
    session_id: int,
    database_session: DatabaseSession,
    as_of_seq: int | None = Query(default=None, alias="asOfSeq", ge=0),
) -> Surface:
    try:
        return SurfaceService(database_session).build_surface(session_id, as_of_seq=as_of_seq)
    except SessionNotFoundError as error:
        raise _session_not_found(error) from error


@router.get("/{session_id}/trajectory", response_model=Trajectory)
def get_session_trajectory(
    session_id: int, database_session: DatabaseSession
) -> Trajectory:
    try:
        return TrajectoryService(database_session).build_trajectory(session_id)
    except SessionNotFoundError as error:
        raise _session_not_found(error) from error


@router.get("/{session_id}/trace", response_model=Trace)
def get_session_trace(
    session_id: int,
    database_session: DatabaseSession,
    run_id: str = Query(min_length=1),
) -> Trace:
    try:
        return TraceService(database_session).build_trace(session_id, run_id)
    except SessionNotFoundError as error:
        raise _session_not_found(error) from error
