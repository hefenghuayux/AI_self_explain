import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.api.questions import DatabaseSession
from app.models.question import Question
from app.models.session import Session
from app.repositories.sessions import SessionRepository
from app.rules.session_lifecycle import (
    FLOW_STAGE_CAPTURING_INPUT,
    FLOW_STAGE_CONFIRMING_TEXT,
    FLOW_STAGE_SHOWING_FULL_SOLUTION,
    FLOW_STAGE_WAIT_INITIAL_CHOICE,
    FLOW_STAGE_WAIT_STUDENT_ACTION,
    STATUS_IN_PROGRESS,
    TERMINAL_STATUSES,
)
from app.schemas.session import (
    AppealInput,
    CreateSessionInput,
    EvaluationRetryInput,
    InitialChoiceInput,
    LearningTimelineItemResponse,
    SessionResponse,
    SolutionUnderstandingInput,
    StudentActionInput,
    TextAttemptInput,
)
from app.services.ai_evaluation import AIEvaluationService
from app.services.ai_support import AISupportService

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


def to_session_response(repository: SessionRepository, session: Session) -> SessionResponse:
    return SessionResponse.model_validate(session).model_copy(
        update={
            "latest_evaluation": repository.get_latest_valid_evaluation(session.id),
            "latest_support": repository.get_latest_valid_support(session.id),
        }
    )


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    session_input: CreateSessionInput, database_session: DatabaseSession
) -> SessionResponse:
    question = database_session.get(Question, session_input.question_id)
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"题目不存在：{session_input.question_id}",
        )
    if question.archived_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已归档题目不能创建会话")
    repository = SessionRepository(database_session)
    return to_session_response(repository, repository.create(session_input.question_id))


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: int, database_session: DatabaseSession) -> SessionResponse:
    repository = SessionRepository(database_session)
    return to_session_response(repository, get_session_or_404(repository, session_id))


@router.get("/{session_id}/timeline", response_model=list[LearningTimelineItemResponse])
def get_learning_timeline(
    session_id: int, database_session: DatabaseSession
) -> list[LearningTimelineItemResponse]:
    repository = SessionRepository(database_session)
    get_session_or_404(repository, session_id)
    return repository.get_student_timeline(session_id)


@router.post("/{session_id}/initial-choice", response_model=SessionResponse)
def choose_initial_choice(
    session_id: int,
    choice_input: InitialChoiceInput,
    database_session: DatabaseSession,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id)
    validate_in_progress(session)
    validate_version(session, choice_input.version)
    if session.flow_stage != FLOW_STAGE_WAIT_INITIAL_CHOICE:
        reject_operation(f"当前流程阶段不能选择初始选项：{session.flow_stage}")
    chosen_session = repository.choose_initial_choice(session, choice_input.choice)
    if choice_input.choice == "NOT_KNOW":
        question = database_session.get(Question, chosen_session.question_id)
        if question is None:
            raise RuntimeError(
                f"会话 {chosen_session.id} 关联题目不存在：{chosen_session.question_id}"
            )
        limited_session = repository.resolve_support_limit(
            session=chosen_session,
            settings=request.app.state.settings,
            trigger_type="FIRST_ROUND_SUPPORT_LIMIT_REACHED",
        )
        if limited_session is not None:
            return to_session_response(repository, limited_session)
        generating_session = repository.begin_support_generation(
            chosen_session, "REQUEST_INITIAL_HINT"
        )
        support_service = AISupportService(database_session, request.app.state.settings)
        chosen_session = support_service.generate_hint(
            question=question, session=generating_session
        )
    return to_session_response(repository, chosen_session)


@router.post("/{session_id}/text-attempts", response_model=SessionResponse)
def submit_text_attempt(
    session_id: int,
    attempt_input: TextAttemptInput,
    database_session: DatabaseSession,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id)
    validate_in_progress(session)
    validate_version(session, attempt_input.version)
    if session.flow_stage != FLOW_STAGE_CAPTURING_INPUT:
        reject_operation(f"当前流程阶段不能提交文本：{session.flow_stage}")
    session, attempt = repository.submit_text(session, attempt_input.confirmed_text)
    evaluated_session = AIEvaluationService(
        database_session, request.app.state.settings
    ).evaluate(
        question=database_session.get(Question, session.question_id),
        session=session,
        attempt=attempt,
    )
    return to_session_response(repository, evaluated_session)


@router.post("/{session_id}/continue", response_model=SessionResponse)
def continue_explaining(
    session_id: int,
    action_input: StudentActionInput,
    database_session: DatabaseSession,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id)
    validate_in_progress(session)
    validate_version(session, action_input.version)
    if session.flow_stage != FLOW_STAGE_WAIT_STUDENT_ACTION:
        reject_operation(f"当前流程阶段不能继续自讲：{session.flow_stage}")
    return to_session_response(repository, repository.continue_explaining(session))


@router.post("/{session_id}/request-support", response_model=SessionResponse)
def request_support(
    session_id: int,
    action_input: StudentActionInput,
    database_session: DatabaseSession,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id)
    validate_in_progress(session)
    validate_version(session, action_input.version)
    if session.flow_stage != FLOW_STAGE_WAIT_STUDENT_ACTION:
        reject_operation(f"当前流程阶段不能请求提示：{session.flow_stage}")
    question = database_session.get(Question, session.question_id)
    if question is None:
        raise RuntimeError(f"会话 {session.id} 关联题目不存在：{session.question_id}")
    limited_session = repository.resolve_support_limit(
        session=session,
        settings=request.app.state.settings,
        trigger_type="SUPPORT_LIMIT_REACHED",
    )
    if limited_session is not None:
        return to_session_response(repository, limited_session)
    generating_session = repository.begin_support_generation(session, "REQUEST_FURTHER_HINT")
    support_service = AISupportService(database_session, request.app.state.settings)
    generated_session = support_service.generate_hint(question=question, session=generating_session)
    return to_session_response(repository, generated_session)


@router.post("/{session_id}/appeal", response_model=SessionResponse)
def appeal(
    session_id: int,
    appeal_input: AppealInput,
    database_session: DatabaseSession,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id)
    validate_in_progress(session)
    validate_version(session, appeal_input.version)
    if session.flow_stage != FLOW_STAGE_WAIT_STUDENT_ACTION:
        reject_operation(f"当前流程阶段不能提交申诉：{session.flow_stage}")
    evaluation = repository.get_latest_valid_evaluation(session.id)
    if evaluation is None:
        reject_operation("尚未获得 AI 评价，不能提交申诉")
    appealed_session = repository.appeal(
        session=session, reason=appeal_input.reason, evaluation_id=evaluation.id
    )
    return to_session_response(repository, appealed_session)


@router.post("/{session_id}/full-solution-understanding", response_model=SessionResponse)
def respond_to_first_solution(
    session_id: int,
    understanding_input: SolutionUnderstandingInput,
    database_session: DatabaseSession,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id)
    validate_in_progress(session)
    validate_version(session, understanding_input.version)
    if session.flow_stage != FLOW_STAGE_SHOWING_FULL_SOLUTION or session.round != 1:
        reject_operation(f"当前流程阶段不能确认第一轮解析理解情况：{session.flow_stage}")
    responded_session = repository.respond_to_first_solution(
        session=session, understood=understanding_input.understood
    )
    return to_session_response(repository, responded_session)


@router.post("/{session_id}/evaluate", response_model=SessionResponse)
def retry_ai_evaluation(
    session_id: int,
    retry_input: EvaluationRetryInput,
    database_session: DatabaseSession,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id)
    validate_in_progress(session)
    validate_version(session, retry_input.version)
    if session.flow_stage != FLOW_STAGE_CONFIRMING_TEXT:
        reject_operation(f"当前流程阶段不能重新评价：{session.flow_stage}")
    attempt = repository.get_latest_attempt(session.id)
    if attempt is None:
        raise RuntimeError(f"会话 {session.id} 缺少可重新评价的确认文本")
    session = repository.begin_ai_evaluation(session, attempt)
    question = database_session.get(Question, session.question_id)
    if question is None:
        raise RuntimeError(f"会话 {session.id} 关联题目不存在：{session.question_id}")
    evaluated_session = AIEvaluationService(
        database_session, request.app.state.settings
    ).evaluate(question=question, session=session, attempt=attempt)
    return to_session_response(repository, evaluated_session)
