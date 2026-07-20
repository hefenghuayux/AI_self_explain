import logging

from fastapi import APIRouter, HTTPException, status

from app.api.questions import DatabaseSession
from app.models.question import Question
from app.models.session import Session
from app.repositories.sessions import SessionRepository
from app.rules.session_lifecycle import (
    FLOW_STAGE_CAPTURING_INPUT,
    FLOW_STAGE_WAIT_INITIAL_CHOICE,
    STATUS_IN_PROGRESS,
    TERMINAL_STATUSES,
)
from app.schemas.session import (
    CreateSessionInput,
    InitialChoiceInput,
    SessionResponse,
    TextAttemptInput,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_session_or_404(repository: SessionRepository, session_id: int) -> Session:
    session = repository.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"会话不存在：{session_id}"
        )
    return session


def reject_operation(detail: str) -> None:
    logger.warning("会话操作被拒绝：%s", detail, extra={"operation": "session_operation_rejected"})
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def validate_version(session: Session, version: int) -> None:
    if session.version != version:
        reject_operation(f"会话版本已变化，当前版本为 {session.version}，请刷新后重试")


def validate_in_progress(session: Session) -> None:
    if session.status in TERMINAL_STATUSES:
        reject_operation(f"终态会话不能继续操作：{session.status}")
    if session.status != STATUS_IN_PROGRESS:
        reject_operation(f"当前会话状态不允许此操作：{session.status}")


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(session_input: CreateSessionInput, database_session: DatabaseSession) -> Session:
    question = database_session.get(Question, session_input.question_id)
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"题目不存在：{session_input.question_id}",
        )
    if question.archived_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已归档题目不能创建会话")
    return SessionRepository(database_session).create(session_input.question_id)


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: int, database_session: DatabaseSession) -> Session:
    return get_session_or_404(SessionRepository(database_session), session_id)


@router.post("/{session_id}/initial-choice", response_model=SessionResponse)
def choose_initial_choice(
    session_id: int,
    choice_input: InitialChoiceInput,
    database_session: DatabaseSession,
) -> Session:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id)
    validate_in_progress(session)
    validate_version(session, choice_input.version)
    if session.flow_stage != FLOW_STAGE_WAIT_INITIAL_CHOICE:
        reject_operation(f"当前流程阶段不能选择初始选项：{session.flow_stage}")
    return repository.choose_initial_choice(session, choice_input.choice)


@router.post("/{session_id}/text-attempts", response_model=SessionResponse)
def submit_text_attempt(
    session_id: int,
    attempt_input: TextAttemptInput,
    database_session: DatabaseSession,
) -> Session:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id)
    validate_in_progress(session)
    validate_version(session, attempt_input.version)
    if session.flow_stage != FLOW_STAGE_CAPTURING_INPUT:
        reject_operation(f"当前流程阶段不能提交文本：{session.flow_stage}")
    return repository.submit_text(session, attempt_input.confirmed_text)
