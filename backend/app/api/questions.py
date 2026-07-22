from fastapi import APIRouter, HTTPException, status

from app.core.auth import CurrentUser, DatabaseSession, TeacherUser
from app.models.question import Question
from app.repositories.questions import QuestionRepository
from app.schemas.question import QuestionInput, QuestionResponse

router = APIRouter(prefix="/questions", tags=["questions"])


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
    _teacher: TeacherUser,
) -> QuestionResponse:
    return QuestionRepository(session).create(question_input)


@router.get("", response_model=list[QuestionResponse])
def list_questions(
    session: DatabaseSession, user: CurrentUser, include_archived: bool = False
) -> list[QuestionResponse]:
    if include_archived and user.role != "TEACHER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="当前账号没有题目管理权限"
        )
    return QuestionRepository(session).list_questions(include_archived=include_archived)


@router.get("/{question_id}", response_model=QuestionResponse)
def get_question(
    question_id: int, session: DatabaseSession, _user: CurrentUser
) -> QuestionResponse:
    repository = QuestionRepository(session)
    return get_question_or_404(repository, question_id)


@router.put("/{question_id}", response_model=QuestionResponse)
def update_question(
    question_id: int,
    question_input: QuestionInput,
    session: DatabaseSession,
    _teacher: TeacherUser,
) -> QuestionResponse:
    repository = QuestionRepository(session)
    question = get_question_or_404(repository, question_id)
    if question.archived_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已归档题目不能编辑")
    return repository.update(question, question_input)


@router.post("/{question_id}/archive", response_model=QuestionResponse)
def archive_question(
    question_id: int, session: DatabaseSession, _teacher: TeacherUser
) -> QuestionResponse:
    repository = QuestionRepository(session)
    question = get_question_or_404(repository, question_id)
    return repository.archive(question)


@router.post("/{question_id}/restore", response_model=QuestionResponse)
def restore_question(
    question_id: int, session: DatabaseSession, _teacher: TeacherUser
) -> QuestionResponse:
    repository = QuestionRepository(session)
    question = get_question_or_404(repository, question_id)
    return repository.restore(question)
