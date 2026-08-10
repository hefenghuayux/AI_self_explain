from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.auth import DatabaseSession, require_teacher
from app.repositories.sessions import SessionRepository
from app.schemas.audit import (
    AuditExportResponse,
    ExternalCallRecordResponse,
    SessionTraceResponse,
    StateTransitionEventResponse,
)
from app.services.audit_trace import AuditTraceService

router = APIRouter(prefix="/sessions", tags=["audit"], dependencies=[Depends(require_teacher)])


def require_session(repository: SessionRepository, session_id: int) -> None:
    if repository.get(session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"会话不存在：{session_id}"
        )


@router.get("/{session_id}/audit/state-events", response_model=list[StateTransitionEventResponse])
def get_state_events(session_id: int, database_session: DatabaseSession):
    repository = SessionRepository(database_session)
    require_session(repository, session_id)
    return repository.get_state_events(session_id)


@router.get("/{session_id}/audit/external-calls", response_model=list[ExternalCallRecordResponse])
def get_external_calls(session_id: int, database_session: DatabaseSession):
    repository = SessionRepository(database_session)
    require_session(repository, session_id)
    return repository.get_external_calls(session_id)


@router.get("/{session_id}/audit/errors", response_model=list[ExternalCallRecordResponse])
def get_external_call_errors(session_id: int, database_session: DatabaseSession):
    repository = SessionRepository(database_session)
    require_session(repository, session_id)
    return repository.get_external_call_errors(session_id)


@router.get("/{session_id}/audit/trace", response_model=SessionTraceResponse)
def get_session_trace(
    session_id: int, request: Request, database_session: DatabaseSession
) -> SessionTraceResponse:
    require_session(SessionRepository(database_session), session_id)
    service = AuditTraceService(database_session, request.app.state.settings.audit_export_dir)
    trace = service.build_session_trace(session_id)
    service.export_session(session_id)
    return trace


@router.post("/{session_id}/audit/export", response_model=AuditExportResponse)
def export_session_trace(
    session_id: int, request: Request, database_session: DatabaseSession
) -> AuditExportResponse:
    require_session(SessionRepository(database_session), session_id)
    return AuditTraceService(
        database_session, request.app.state.settings.audit_export_dir
    ).export_session(session_id)
