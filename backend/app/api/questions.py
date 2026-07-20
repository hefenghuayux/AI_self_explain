from collections.abc import Generator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.models.question import Question
from app.repositories.questions import QuestionRepository
from app.schemas.question import QuestionInput, QuestionResponse

router = APIRouter(prefix="/questions", tags=["questions"])


def get_database_session(request: Request) -> Generator[Session, None, None]:
    session: Session = request.app.state.database_session_factory()
    try:
        yield session
    finally:
        session.close()


DatabaseSession = Annotated[Session, Depends(get_database_session)]


def get_question_or_404(repository: QuestionRepository, question_id: int) -> Question:
    question = repository.get(question_id)
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"题目不存在：{question_id}"
        )
    return question


@router.post("", response_model=QuestionResponse, status_code=status.HTTP_201_CREATED)
def create_question(
    question_input: QuestionInput,
    session: DatabaseSession,
) -> QuestionResponse:
    return QuestionRepository(session).create(question_input)


@router.get("", response_model=list[QuestionResponse])
def list_questions(
    session: DatabaseSession, include_archived: bool = False
) -> list[QuestionResponse]:
    return QuestionRepository(session).list_questions(include_archived=include_archived)


@router.get("/{question_id}", response_model=QuestionResponse)
def get_question(question_id: int, session: DatabaseSession) -> QuestionResponse:
    repository = QuestionRepository(session)
    return get_question_or_404(repository, question_id)


@router.put("/{question_id}", response_model=QuestionResponse)
def update_question(
    question_id: int,
    question_input: QuestionInput,
    session: DatabaseSession,
) -> QuestionResponse:
    repository = QuestionRepository(session)
    question = get_question_or_404(repository, question_id)
    if question.archived_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已归档题目不能编辑")
    return repository.update(question, question_input)


@router.post("/{question_id}/archive", response_model=QuestionResponse)
def archive_question(question_id: int, session: DatabaseSession) -> QuestionResponse:
    repository = QuestionRepository(session)
    question = get_question_or_404(repository, question_id)
    return repository.archive(question)


@router.post("/{question_id}/restore", response_model=QuestionResponse)
def restore_question(question_id: int, session: DatabaseSession) -> QuestionResponse:
    repository = QuestionRepository(session)
    question = get_question_or_404(repository, question_id)
    return repository.restore(question)
