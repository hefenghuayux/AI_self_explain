from fastapi import APIRouter, HTTPException, status

from app.api.questions import DatabaseSession
from app.repositories.sessions import SessionRepository
from app.schemas.audit import ExternalCallRecordResponse, StateTransitionEventResponse

router = APIRouter(prefix="/sessions", tags=["audit"])


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
