from fastapi import APIRouter, HTTPException, Query, status

from app.core.auth import CurrentUser, DatabaseSession, TeacherUser
from app.models.question import Question
from app.repositories.questions import QuestionRepository
from app.schemas.question import (
    QuestionFilterOptionsResponse,
    QuestionInput,
    QuestionListQuery,
    QuestionListResponse,
    QuestionPaginationResponse,
    QuestionResponse,
)

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


def validate_include_archived_permission(include_archived: bool, user_role: str) -> None:
    if include_archived and user_role != "TEACHER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="当前账号没有题目管理权限"
        )


@router.get("/filter-options", response_model=QuestionFilterOptionsResponse)
def list_question_filter_options(
    session: DatabaseSession, user: CurrentUser, include_archived: bool = False
) -> QuestionFilterOptionsResponse:
    validate_include_archived_permission(include_archived, user.role)
    grade_periods, subjects = QuestionRepository(session).list_filter_options(
        include_archived=include_archived
    )
    return QuestionFilterOptionsResponse(grade_periods=grade_periods, subjects=subjects)


@router.get("", response_model=QuestionListResponse)
def list_questions(
    session: DatabaseSession,
    user: CurrentUser,
    include_archived: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    grade_period: int | None = None,
    subject: str | None = None,
    keyword: str | None = None,
) -> QuestionListResponse:
    validate_include_archived_permission(include_archived, user.role)
    query = QuestionListQuery(
        page=page,
        page_size=page_size,
        grade_period=grade_period,
        subject=subject,
        keyword=keyword,
    )
    questions, total = QuestionRepository(session).list_questions(
        query, include_archived=include_archived
    )
    return QuestionListResponse(
        items=questions,
        pagination=QuestionPaginationResponse(
            page=query.page,
            page_size=query.page_size,
            total=total,
            total_pages=(total + query.page_size - 1) // query.page_size,
        ),
    )


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
