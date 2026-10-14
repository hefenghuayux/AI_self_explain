import asyncio
import json
import logging
import time

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from app.api.teacher_speech import prewarm_teacher_reply
from app.core.auth import CurrentUser, DatabaseSession, get_current_user
from app.core.logging import bind_trace_context, new_correlation_id, reset_trace_context
from app.models.explanation_attempt import ExplanationAttempt
from app.models.question import Question
from app.models.session import Session
from app.repositories.sessions import (
    SessionRepository,
    SessionVersionConflict,
    _format_guided_answers_for_timeline,
    _format_mastery_answers_for_timeline,
    session_appeal_run_id,
    session_run_id,
)
from app.rules.session_lifecycle import (
    FLOW_STAGE_CAPTURING_INPUT,
    FLOW_STAGE_SHOWING_FULL_SOLUTION,
    FLOW_STAGE_WAIT_GUIDED_ANSWERS,
    FLOW_STAGE_WAIT_INITIAL_CHOICE,
    FLOW_STAGE_WAIT_MASTERY_CHECK,
    FLOW_STAGE_WAIT_STUDENT_ACTION,
    STATUS_IN_PROGRESS,
    STATUS_PAUSED,
    STUDENT_INTERRUPTION_FLOW_STAGES,
    TERMINAL_STATUSES,
    can_pause,
    can_submit_student_interruption,
)
from app.rules.teaching_decision import decide_teaching
from app.schemas.ai_evaluation import AIEvaluationResponse
from app.schemas.mastery_check import MasteryCheckQuestion
from app.schemas.session import (
    AppealInput,
    CreateSessionInput,
    DoubtRequestInput,
    GuidedAnswersInput,
    HelpRequestInput,
    InitialChoiceInput,
    LearningTimelineItemResponse,
    MasteryCheckAnswersInput,
    MasteryCheckResponse,
    SessionHistoryItemResponse,
    SessionResponse,
    SolutionUnderstandingInput,
    StudentActionInput,
    TeachingGenerationResponse,
    TeachingNotRequiredResponse,
    TeachingSucceededResponse,
    TextAttemptInput,
    VoiceInputTarget,
)
from app.schemas.session_step import StepAttemptInput, StepsResponse
from app.schemas.support import GuidedAnswer, SupportEventResponse
from app.services.ai_evaluation import AIEvaluationService
from app.services.ai_mastery_check import (
    AIMasteryCheckService,
    MasteryCheckQuestionInput,
    mastery_check_run_id,
)
from app.services.ai_support import AISupportService, support_run_id
from app.services.ai_teaching import AITeachingService
from app.services.audio_storage import AudioStorage, AudioStorageError
from app.services.context_compaction import CompactionError
from app.services.context_runtime import preflight_submission
from app.services.realtime_asr import ASRServiceError, ASRStreamEvent, RealtimeASRService

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/sessions", tags=["sessions"], dependencies=[Depends(get_current_user)]
)


def get_session_or_404(
    repository: SessionRepository, session_id: int, current_user: CurrentUser
) -> Session:
    session = repository.get(session_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"会话不存在：{session_id}"
        )
    return session


def reject_operation(detail: str) -> None:
    logger.warning("会话操作被拒绝：%s", detail, extra={"operation": "session_operation_rejected"})
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def validate_version(session: Session, version: int) -> None:
    if session.version != version:
        raise HTTPException(status_code=409, detail={
            "code": "SESSION_VERSION_CONFLICT",
            "message": "会话版本已变化，请刷新后重试",
            "sessionId": session.id,
        })


def validate_in_progress(session: Session) -> None:
    if session.status in TERMINAL_STATUSES:
        reject_operation(f"终态会话不能继续操作：{session.status}")
    if session.status != STATUS_IN_PROGRESS:
        reject_operation(f"当前会话状态不允许此操作：{session.status}")


def validate_pauseable(session: Session) -> None:
    if session.status in TERMINAL_STATUSES:
        reject_operation(f"终态会话不能暂停：{session.status}")
    if session.status != STATUS_IN_PROGRESS:
        reject_operation(f"当前会话状态不允许暂停：{session.status}")
    if not can_pause(session.flow_stage):
        reject_operation(f"当前流程阶段不能暂停：{session.flow_stage}")


def to_session_response(
    repository: SessionRepository,
    session: Session,
    teaching_generation: TeachingGenerationResponse | None = None,
) -> SessionResponse:
    latest_support = repository.get_latest_valid_support(session.id)
    latest_evaluation = repository.get_latest_valid_evaluation(session.id)
    mastery_check = repository.get_latest_mastery_check(session.id)
    return SessionResponse.model_validate(session).model_copy(
        update={
            "latest_evaluation": (
                AIEvaluationResponse.model_validate(latest_evaluation)
                if latest_evaluation is not None
                else None
            ),
            "latest_support": (
                SupportEventResponse.model_validate(latest_support)
                if latest_support is not None
                else None
            ),
            "teaching_generation": teaching_generation,
            "mastery_check": (
                _mastery_check_response(mastery_check) if mastery_check is not None else None
            ),
        }
    )


def _mastery_check_response(mastery_check) -> MasteryCheckResponse:
    """只投影学生可见字段：问题、回答、评价结论；证据引用与内部字段不外发。"""
    return MasteryCheckResponse.model_validate(
        {
            "questions": [
                {"id": question["id"], "question": question["question"]}
                for question in mastery_check.questions
                if isinstance(question, dict) and "id" in question and "question" in question
            ],
            "answers": mastery_check.answers,
            "results": mastery_check.results,
            "outcome": mastery_check.outcome,
        }
    )


def start_mastery_check(
    *,
    repository: SessionRepository,
    session: Session,
    question: Question,
    settings,
    http_client,
    failure_flow_stage: str = FLOW_STAGE_CAPTURING_INPUT,
) -> Session:
    """生成并保存核验问题。

    核验问题只依据题目上下文与共享历史，评价结论不进入提示词；最近一次非终态
    评价仅用于把核验记录关联到对应的自讲尝试。缺少可关联的尝试时走现有
    人工复核路径；AI 传输失败则恢复到调用前的可重试阶段。
    """
    linked_evaluation = repository.get_latest_non_terminal_evaluation(session.id)
    linked_attempt = (
        None
        if linked_evaluation is None
        else repository.get_attempt(session.id, linked_evaluation.attempt_id)
    )
    if linked_evaluation is not None and linked_attempt is not None:
        output = AIMasteryCheckService(
            repository.database_session, settings, http_client
        ).generate_questions(
            question=question,
            session=session,
            failure_flow_stage=failure_flow_stage,
        )
        if output is not None:
            repository.record_mastery_questions(
                session=session,
                attempt_id=linked_attempt.id,
                evaluation_id=linked_evaluation.id,
                questions=output.questions,
            )
            return session
        if session.flow_stage != FLOW_STAGE_WAIT_MASTERY_CHECK:
            # AI 结构失败时，核验服务已经申请过人工复核。
            return session
    return repository.request_human_review(
        session=session,
        need_human_reason="缺少可用于核验的评价证据，已转人工复核",
        trigger_type="AI_MASTERY_CHECK_EVIDENCE_MISSING",
    )


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    session_input: CreateSessionInput,
    database_session: DatabaseSession,
    current_user: CurrentUser,
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
    created_session = repository.create_or_resume(
        session_input.question_id, current_user.id, restart=session_input.restart
    )
    return to_session_response(repository, created_session)


def get_voice_attempt_for_submission(
    repository: SessionRepository,
    session: Session,
    attempt_id: int,
    target: VoiceInputTarget,
    target_id: str | None = None,
):
    attempt = repository.get_voice_attempt(session.id, attempt_id)
    if attempt is None or attempt.confirmed_text is not None:
        reject_operation("语音转写不存在、已提交或已变化")
    if attempt.voice_target != target or attempt.voice_target_id != target_id:
        reject_operation("语音转写目标与当前提交不一致")
    return attempt


@router.get("/history", response_model=list[SessionHistoryItemResponse])
def list_session_history(
    database_session: DatabaseSession,
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=50),
) -> list[SessionHistoryItemResponse]:
    sessions = SessionRepository(database_session).list_history(current_user.id, limit)
    return [
        SessionHistoryItemResponse(
            id=session.id,
            name=f"自讲{index}",
            status=session.status,
            created_at=session.created_at,
        )
        for index, session in enumerate(sessions, start=1)
    ]


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: int, database_session: DatabaseSession, current_user: CurrentUser
) -> SessionResponse:
    repository = SessionRepository(database_session)
    return to_session_response(repository, get_session_or_404(repository, session_id, current_user))


@router.get("/{session_id}/timeline", response_model=list[LearningTimelineItemResponse])
def get_learning_timeline(
    session_id: int, database_session: DatabaseSession, current_user: CurrentUser
) -> list[LearningTimelineItemResponse]:
    repository = SessionRepository(database_session)
    get_session_or_404(repository, session_id, current_user)
    return repository.get_student_timeline(session_id)


@router.post("/{session_id}/pause", response_model=SessionResponse)
def pause_session(
    session_id: int,
    action_input: StudentActionInput,
    database_session: DatabaseSession,
    current_user: CurrentUser,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    validate_version(session, action_input.version)
    validate_pauseable(session)
    return to_session_response(repository, repository.pause(session))


@router.post("/{session_id}/resume", response_model=SessionResponse)
def resume_session(
    session_id: int,
    action_input: StudentActionInput,
    database_session: DatabaseSession,
    current_user: CurrentUser,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    validate_version(session, action_input.version)
    if session.status != STATUS_PAUSED:
        reject_operation(f"当前会话状态不允许恢复：{session.status}")
    return to_session_response(repository, repository.resume(session))


@router.post("/{session_id}/initial-choice", response_model=SessionResponse)
def choose_initial_choice(
    session_id: int,
    choice_input: InitialChoiceInput,
    database_session: DatabaseSession,
    current_user: CurrentUser,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    validate_in_progress(session)
    validate_version(session, choice_input.version)
    if session.flow_stage != FLOW_STAGE_WAIT_INITIAL_CHOICE:
        reject_operation(f"当前流程阶段不能选择初始选项：{session.flow_stage}")
    chosen_session = repository.choose_initial_choice(session, choice_input.choice)
    return to_session_response(repository, chosen_session)


@router.post("/{session_id}/text-attempts", response_model=SessionResponse)
def submit_text_attempt(
    session_id: int,
    attempt_input: TextAttemptInput,
    database_session: DatabaseSession,
    current_user: CurrentUser,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    validate_in_progress(session)
    if session.flow_stage != FLOW_STAGE_CAPTURING_INPUT:
        reject_operation(f"当前流程阶段不能提交文本：{session.flow_stage}")
    validate_version(session, attempt_input.version)
    preflight_submission(
        database_session, session, request.app.state.settings, text=attempt_input.confirmed_text
    )
    voice_attempt = None
    if attempt_input.voice_attempt_id is not None:
        voice_attempt = get_voice_attempt_for_submission(
            repository,
            session,
            attempt_input.voice_attempt_id,
            "SELF_EXPLANATION",
        )
    try:
        session, attempt = repository.submit_text(
            session,
            attempt_input.confirmed_text,
            expected_version=attempt_input.version,
            voice_attempt=voice_attempt,
        )
    except SessionVersionConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SESSION_VERSION_CONFLICT",
                "message": "会话版本已变化，请刷新后重试",
                "sessionId": session_id,
            },
        ) from error
    return evaluate_explanation_attempt(
        repository=repository,
        session=session,
        attempt=attempt,
        database_session=database_session,
        request=request,
    )


@router.get("/{session_id}/steps", response_model=StepsResponse)
def get_session_steps(
    session_id: int,
    database_session: DatabaseSession,
    current_user: CurrentUser,
    round: str = Query(default="current"),
) -> StepsResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    if round != "current":
        try:
            requested_round = int(round)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="round 必须是 current 或整数") from error
        if requested_round != session.round:
            reject_operation("当前仅支持查询本轮自讲步骤")
    return StepsResponse.model_validate(repository.get_current_steps(session))


@router.post("/{session_id}/step-attempts", response_model=SessionResponse)
def submit_step_attempt(
    session_id: int,
    attempt_input: StepAttemptInput,
    database_session: DatabaseSession,
    current_user: CurrentUser,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    validate_in_progress(session)
    if session.flow_stage != FLOW_STAGE_CAPTURING_INPUT:
        reject_operation(f"当前流程阶段不能提交步骤：{session.flow_stage}")
    validate_version(session, attempt_input.version)
    try:
        current_step_id = session.current_step_id
        if current_step_id is None:
            raise ValueError("当前自讲草稿不存在")
        explanation, projection = repository.build_step_snapshot(
            session=session,
            current_step_id=current_step_id,
            current_step_content=attempt_input.current_step_content,
        )
    except ValueError as error:
        reject_operation(str(error))
    preflight_submission(
        database_session,
        session,
        request.app.state.settings,
        attempt=ExplanationAttempt(
            confirmed_text=projection,
            student_explanation=explanation,
        ),
    )
    try:
        session, attempt = repository.submit_step_attempt(
            session=session,
            current_step_id=current_step_id,
            current_step_content=attempt_input.current_step_content,
            expected_version=attempt_input.version,
        )
    except SessionVersionConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SESSION_VERSION_CONFLICT",
                "message": "会话版本已变化，请刷新后重试",
                "sessionId": session_id,
            },
        ) from error
    return evaluate_explanation_attempt(
        repository=repository,
        session=session,
        attempt=attempt,
        database_session=database_session,
        request=request,
    )


@prewarm_teacher_reply
def evaluate_explanation_attempt(
    *,
    repository: SessionRepository,
    session: Session,
    attempt: ExplanationAttempt,
    database_session: DatabaseSession,
    request: Request,
) -> SessionResponse:
    question = database_session.get(Question, session.question_id)
    if question is None:
        raise RuntimeError(f"会话 {session.id} 关联题目不存在：{session.question_id}")
    try:
        evaluation_result = AIEvaluationService(
            database_session, request.app.state.settings, request.app.state.ai_http_client
        ).evaluate(
            question=question,
            session=session,
            attempt=attempt,
        )
    except CompactionError as error:
        if error.is_service_failure:
            raise
        repository.request_human_review(
            session=session,
            need_human_reason=f"AI 评价上下文恢复失败：{error.code}",
            trigger_type="AI_EVALUATION_CONTEXT_FAILED",
            related_attempt_id=attempt.id,
            run_id=session_run_id(session.id, attempt.id),
        )
        raise
    if isinstance(evaluation_result, Session):
        return to_session_response(repository, evaluation_result)

    evaluation_output = evaluation_result.output
    decision = decide_teaching(
        evaluation=evaluation_output,
        session=session,
        settings=request.app.state.settings,
        evaluation_mode=evaluation_result.evaluation_record.evaluation_mode,
    )
    if not decision.should_generate:
        decided_session, _ = repository.apply_teaching_decision(
            session=session,
            evaluation_id=evaluation_result.evaluation_record.id,
            decision=decision,
            teaching_output=None,
            run_id=session_run_id(session.id, attempt.id),
        )
        if decision.start_mastery_check:
            decided_session = start_mastery_check(
                repository=repository,
                session=decided_session,
                question=question,
                settings=request.app.state.settings,
                http_client=request.app.state.ai_http_client,
            )
        return to_session_response(
            repository,
            decided_session,
            TeachingNotRequiredResponse(status="NOT_REQUIRED"),
        )

    try:
        teaching_output = AITeachingService(
            database_session, request.app.state.settings, request.app.state.ai_http_client
        ).generate(
            question=question,
            session=session,
            attempt=attempt,
            evaluation=evaluation_output,
            decision=decision,
        )
    except CompactionError as error:
        if error.is_service_failure:
            raise
        repository.record_teaching_generation_failure(
            session=session,
            evaluation_id=evaluation_result.evaluation_record.id,
            decision=decision,
            run_id=session_run_id(session.id, attempt.id),
        )
        raise
    if teaching_output is None:
        failed_session = repository.record_teaching_generation_failure(
            session=session,
            evaluation_id=evaluation_result.evaluation_record.id,
            decision=decision,
            run_id=session_run_id(session.id, attempt.id),
        )
        return to_session_response(repository, failed_session)

    decided_session, support_event = repository.apply_teaching_decision(
        session=session,
        evaluation_id=evaluation_result.evaluation_record.id,
        decision=decision,
        teaching_output=teaching_output,
        run_id=session_run_id(session.id, attempt.id),
    )
    if support_event is None:
        raise RuntimeError("教学输出校验成功后缺少支持事件")
    return to_session_response(
        repository,
        decided_session,
        TeachingSucceededResponse(status="SUCCEEDED", support_event_id=support_event.id),
    )


@router.post("/{session_id}/continue", response_model=SessionResponse)
def continue_explaining(
    session_id: int,
    action_input: StudentActionInput,
    database_session: DatabaseSession,
    current_user: CurrentUser,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    validate_in_progress(session)
    validate_version(session, action_input.version)
    if session.flow_stage != FLOW_STAGE_WAIT_STUDENT_ACTION:
        reject_operation(f"当前流程阶段不能继续自讲：{session.flow_stage}")
    return to_session_response(repository, repository.continue_explaining(session))


@router.post("/{session_id}/request-support", response_model=SessionResponse)
@prewarm_teacher_reply
def request_support(
    session_id: int,
    action_input: HelpRequestInput,
    database_session: DatabaseSession,
    current_user: CurrentUser,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    validate_in_progress(session)
    validate_version(session, action_input.version)
    if session.flow_stage != FLOW_STAGE_WAIT_STUDENT_ACTION:
        reject_operation(f"当前流程阶段不能请求提示：{session.flow_stage}")
    preflight_submission(
        database_session, session, request.app.state.settings, main_draft=action_input.main_draft
    )
    question = database_session.get(Question, session.question_id)
    if question is None:
        raise RuntimeError(f"会话 {session.id} 关联题目不存在：{session.question_id}")
    repository.record_support_submission(
        session=session,
        main_draft=action_input.main_draft,
        doubt_text=None,
    )
    # 学生输入与随后的支持生成共用一次运行，轨迹里两者属于同一轮。
    run_id = support_run_id(session)
    # main_draft 允许为空（学生没写草稿就直接请求提示），空文本没有可记录的内容。
    if action_input.main_draft.strip():
        repository.record_user_message(
            session=session,
            run_id=run_id,
            text=action_input.main_draft,
            input_type="text",
        )
    limited_session = repository.resolve_support_limit(
        session=session,
        settings=request.app.state.settings,
        trigger_type="SUPPORT_LIMIT_REACHED",
    )
    if limited_session is not None:
        return to_session_response(repository, limited_session)
    support_service = AISupportService(
        database_session, request.app.state.settings, request.app.state.ai_http_client
    )
    output = support_service.generate_request(
        question=question,
        session=session,
        main_draft=action_input.main_draft,
        doubt_text=None,
        run_id=run_id,
    )
    if output is None:
        return to_session_response(repository, session)
    generated_session = apply_support_request_output(
        repository=repository,
        session=session,
        main_draft=action_input.main_draft,
        doubt_text=None,
        output=output,
        settings=request.app.state.settings,
    )
    return to_session_response(repository, generated_session)


@router.post("/{session_id}/ask-doubt", response_model=SessionResponse)
@prewarm_teacher_reply
def ask_doubt(
    session_id: int,
    action_input: DoubtRequestInput,
    database_session: DatabaseSession,
    current_user: CurrentUser,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    validate_in_progress(session)
    validate_version(session, action_input.version)
    if not can_submit_student_interruption(session.flow_stage):
        reject_operation(f"当前流程阶段不能提出疑问：{session.flow_stage}")
    preflight_submission(
        database_session, session, request.app.state.settings,
        main_draft=action_input.main_draft, doubt_text=action_input.doubt_text,
    )
    question = database_session.get(Question, session.question_id)
    if question is None:
        raise RuntimeError(f"会话 {session.id} 关联题目不存在：{session.question_id}")
    if action_input.voice_attempt_id is not None:
        voice_attempt = get_voice_attempt_for_submission(
            repository,
            session,
            action_input.voice_attempt_id,
            "DOUBT",
        )
        repository.mark_voice_attempt_submitted(
            attempt=voice_attempt, confirmed_text=action_input.doubt_text
        )
    repository.record_support_submission(
        session=session,
        main_draft=action_input.main_draft,
        doubt_text=action_input.doubt_text,
    )
    # 学生输入与随后的支持生成共用一次运行，轨迹里两者属于同一轮。
    run_id = support_run_id(session)
    repository.record_user_message(
        session=session,
        run_id=run_id,
        text=action_input.doubt_text,
        input_type="voice" if action_input.voice_attempt_id is not None else "text",
    )
    support_service = AISupportService(
        database_session, request.app.state.settings, request.app.state.ai_http_client
    )
    output = support_service.generate_request(
        question=question,
        session=session,
        main_draft=action_input.main_draft,
        doubt_text=action_input.doubt_text,
        run_id=run_id,
    )
    if output is None:
        return to_session_response(repository, session)
    generated_session = apply_support_request_output(
        repository=repository,
        session=session,
        main_draft=action_input.main_draft,
        doubt_text=action_input.doubt_text,
        output=output,
        settings=request.app.state.settings,
    )
    return to_session_response(repository, generated_session)


@router.post("/{session_id}/guided-answers", response_model=SessionResponse)
@prewarm_teacher_reply
def submit_guided_answers(
    session_id: int,
    action_input: GuidedAnswersInput,
    database_session: DatabaseSession,
    current_user: CurrentUser,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    validate_in_progress(session)
    validate_version(session, action_input.version)
    if session.flow_stage != FLOW_STAGE_WAIT_GUIDED_ANSWERS:
        reject_operation(f"当前流程阶段不能提交子问题答案：{session.flow_stage}")
    support_event = repository.get_pending_guided_support(session.id)
    if support_event is None:
        raise RuntimeError(f"会话 {session.id} 缺少待回答的子问题支持事件")
    question_ids = [
        str(item["id"])
        for item in support_event.guided_questions or []
        if "id" in item
    ]
    submitted_by_id = {answer.question_id: answer for answer in action_input.answers}
    if len(submitted_by_id) != len(action_input.answers):
        reject_operation("同一次提交不能包含重复的子问题答案")
    unknown_question_ids = set(submitted_by_id) - set(question_ids)
    if unknown_question_ids:
        reject_operation(f"提交了不存在的子问题：{sorted(unknown_question_ids)}")
    existing_answers = [
        GuidedAnswer.model_validate(answer) for answer in support_event.guided_answers or []
    ]
    existing_by_id = {answer.question_id: answer for answer in existing_answers}
    repeated_question_ids = set(submitted_by_id) & set(existing_by_id)
    if repeated_question_ids:
        reject_operation(f"子问题已经提交过答案：{sorted(repeated_question_ids)}")
    merged_by_id = {**existing_by_id, **submitted_by_id}
    merged_answers = [
        merged_by_id[question_id]
        for question_id in question_ids
        if question_id in merged_by_id
    ]
    if len(merged_answers) < len(question_ids):
        if action_input.voice_attempt_id is not None:
            if len(action_input.answers) != 1:
                reject_operation("语音转写一次只能关联一个子问题答案")
            answer = action_input.answers[0]
            voice_attempt = get_voice_attempt_for_submission(
                repository,
                session,
                action_input.voice_attempt_id,
                "GUIDED_ANSWER",
                answer.question_id,
            )
            repository.mark_voice_attempt_submitted(
                attempt=voice_attempt, confirmed_text=answer.answer
            )
        # 只答了一部分子问题时没有 AI 调用，这次输入自成一次运行。
        repository.record_user_message(
            session=session,
            run_id=support_run_id(session),
            text=_format_guided_answers_for_timeline(
                support_event.guided_questions or [], action_input.answers
            ),
            input_type="voice" if action_input.voice_attempt_id is not None else "text",
        )
        updated_session = repository.record_partial_guided_answers(
            session=session,
            support_event=support_event,
            submitted_answers=action_input.answers,
            merged_answers=merged_answers,
        )
        return to_session_response(repository, updated_session)
    preflight_submission(
        database_session, session, request.app.state.settings,
        support_event=support_event, answers=merged_answers,
    )
    question = database_session.get(Question, session.question_id)
    if question is None:
        raise RuntimeError(f"会话 {session.id} 关联题目不存在：{session.question_id}")
    if action_input.voice_attempt_id is not None:
        if len(action_input.answers) != 1:
            reject_operation("语音转写一次只能关联一个子问题答案")
        answer = action_input.answers[0]
        voice_attempt = get_voice_attempt_for_submission(
            repository,
            session,
            action_input.voice_attempt_id,
            "GUIDED_ANSWER",
            answer.question_id,
        )
        repository.mark_voice_attempt_submitted(
            attempt=voice_attempt, confirmed_text=answer.answer
        )
    support_service = AISupportService(
        database_session, request.app.state.settings, request.app.state.ai_http_client
    )
    # 学生输入与随后的答案评估共用一次运行，轨迹里两者属于同一轮。
    run_id = support_run_id(session)
    repository.record_user_message(
        session=session,
        run_id=run_id,
        text=_format_guided_answers_for_timeline(
            support_event.guided_questions or [], action_input.answers
        ),
        input_type="voice" if action_input.voice_attempt_id is not None else "text",
    )
    assessment = support_service.assess_guided_answers(
        question=question,
        session=session,
        support_event=support_event,
        answers=merged_answers,
        run_id=run_id,
    )
    if assessment is None:
        return to_session_response(repository, session)
    updated_session = repository.record_guided_answers(
        session=session,
        support_event=support_event,
        submitted_answers=action_input.answers,
        merged_answers=merged_answers,
        follow_up_content=assessment.content,
    )
    return to_session_response(repository, updated_session)


@router.post("/{session_id}/appeal", response_model=SessionResponse)
def appeal(
    session_id: int,
    appeal_input: AppealInput,
    database_session: DatabaseSession,
    current_user: CurrentUser,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    validate_in_progress(session)
    validate_version(session, appeal_input.version)
    if not can_submit_student_interruption(session.flow_stage):
        reject_operation(f"当前流程阶段不能提交申诉：{session.flow_stage}")
    evaluation = repository.get_latest_valid_evaluation(session.id)
    if evaluation is None and repository.get_latest_valid_support(session.id) is None:
        reject_operation("尚未获得可申诉的 AI 回复")
    if appeal_input.voice_attempt_id is not None:
        voice_attempt = get_voice_attempt_for_submission(
            repository,
            session,
            appeal_input.voice_attempt_id,
            "APPEAL",
        )
        repository.mark_voice_attempt_submitted(
            attempt=voice_attempt, confirmed_text=appeal_input.reason
        )
    appealed_session = repository.appeal(
        session=session,
        reason=appeal_input.reason,
        evaluation_id=evaluation.id if evaluation is not None else None,
        run_id=session_appeal_run_id(session.id, session.version),
        input_type="voice" if appeal_input.voice_attempt_id is not None else "text",
    )
    return to_session_response(repository, appealed_session)


@router.post("/{session_id}/full-solution-understanding", response_model=SessionResponse)
@prewarm_teacher_reply
def respond_to_first_solution(
    session_id: int,
    understanding_input: SolutionUnderstandingInput,
    database_session: DatabaseSession,
    current_user: CurrentUser,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    validate_in_progress(session)
    validate_version(session, understanding_input.version)
    if session.flow_stage != FLOW_STAGE_SHOWING_FULL_SOLUTION:
        reject_operation(f"当前流程阶段不能确认第一轮解析理解情况：{session.flow_stage}")
    latest_evaluation = repository.get_latest_valid_evaluation(session.id)
    responded_session = repository.respond_to_first_solution(
        session=session,
        evaluation_id=None if latest_evaluation is None else latest_evaluation.id,
        understood=understanding_input.understood,
    )
    if responded_session.flow_stage == FLOW_STAGE_WAIT_MASTERY_CHECK:
        question = database_session.get(Question, responded_session.question_id)
        if question is None:
            raise RuntimeError(f"会话 {session.id} 关联题目不存在：{session.question_id}")
        responded_session = start_mastery_check(
            repository=repository,
            session=responded_session,
            question=question,
            settings=request.app.state.settings,
            http_client=request.app.state.ai_http_client,
            failure_flow_stage=FLOW_STAGE_SHOWING_FULL_SOLUTION,
        )
    return to_session_response(repository, responded_session)


@router.post("/{session_id}/mastery-check-answers", response_model=SessionResponse)
def submit_mastery_check_answers(
    session_id: int,
    answers_input: MasteryCheckAnswersInput,
    database_session: DatabaseSession,
    current_user: CurrentUser,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id, current_user)
    validate_in_progress(session)
    validate_version(session, answers_input.version)
    if session.flow_stage != FLOW_STAGE_WAIT_MASTERY_CHECK:
        reject_operation(f"当前流程阶段不能提交核验回答：{session.flow_stage}")
    mastery_check = repository.get_latest_mastery_check(session.id)
    if mastery_check is None:
        raise RuntimeError(f"会话 {session.id} 缺少待回答的核验记录")
    if mastery_check.outcome is not None:
        reject_operation("本次核验已经提交过回答")
    stored_questions = [
        MasteryCheckQuestion.model_validate(question)
        for question in mastery_check.questions
        if isinstance(question, dict)
    ]
    expected_ids = [question.id for question in stored_questions]
    submitted_ids = [answer.question_id for answer in answers_input.answers]
    if set(submitted_ids) != set(expected_ids) or len(submitted_ids) != len(expected_ids):
        reject_operation("核验回答必须与已发送问题一一对应")
    question = database_session.get(Question, session.question_id)
    if question is None:
        raise RuntimeError(f"会话 {session.id} 关联题目不存在：{session.question_id}")
    question_inputs = [
        MasteryCheckQuestionInput(
            question_id=item.id,
            question=item.question,
            evidence_refs=[ref.model_dump() for ref in item.evidence_refs],
        )
        for item in stored_questions
    ]
    # 学生输入与随后的回答评价共用一次运行，轨迹里两者属于同一轮。
    run_id = mastery_check_run_id(session, "MASTERY_CHECK_ASSESSMENT")
    repository.record_user_message(
        session=session,
        run_id=run_id,
        text=_format_mastery_answers_for_timeline(
            mastery_check.questions, [answer.model_dump() for answer in answers_input.answers]
        ),
        input_type="text",
    )
    try:
        output = AIMasteryCheckService(
            database_session, request.app.state.settings, request.app.state.ai_http_client
        ).evaluate_answers(
            question=question,
            session=session,
            questions=question_inputs,
            answers=answers_input.answers,
            run_id=run_id,
        )
    except CompactionError as error:
        if error.is_service_failure:
            raise
        repository.request_human_review(
            session=session,
            need_human_reason=f"AI 核验上下文恢复失败：{error.code}",
            trigger_type="AI_MASTERY_CHECK_CONTEXT_FAILED",
        )
        raise
    if output is None:
        return to_session_response(repository, session)
    updated_session, _ = repository.record_mastery_answers(
        session=session,
        mastery_check=mastery_check,
        answers=answers_input.answers,
        results=output.results,
    )
    return to_session_response(repository, updated_session)


async def reject_voice_stream(websocket: WebSocket, detail: str) -> None:
    await websocket.send_json({"type": "error", "message": detail})
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)


async def start_realtime_asr(
    *,
    settings,
    repository: SessionRepository,
    session: Session,
    start_attempt_number: int,
) -> tuple[RealtimeASRService | None, int, float | None]:
    for attempt_number in range(start_attempt_number, settings.asr_transport_max_retries + 2):
        started_at = time.perf_counter()
        service = RealtimeASRService(settings=settings, loop=asyncio.get_running_loop())
        try:
            await asyncio.wait_for(
                asyncio.to_thread(service.start), timeout=settings.asr_request_timeout_seconds
            )
            return service, attempt_number, started_at
        except (ASRServiceError, AudioStorageError, TimeoutError) as error:
            error_type = "ASR_TIMEOUT" if isinstance(error, TimeoutError) else "ASR_SERVICE_ERROR"
            error_message = str(error) or "建立实时 ASR 连接超时"
            repository.record_external_call(
                session=session,
                call_type="ASR",
                attempt_number=attempt_number,
                transport_status="ERROR",
                duration_ms=round((time.perf_counter() - started_at) * 1000),
                provider=settings.asr_provider,
                model=settings.asr_model,
                error_type=error_type,
                error_message=error_message,
            )
            if attempt_number >= settings.asr_transport_max_retries + 1:
                return None, attempt_number, None
            await asyncio.sleep(settings.asr_retry_backoff_seconds[attempt_number - 1])
    raise RuntimeError("实时 ASR 重试循环异常结束")


@router.websocket("/{session_id}/voice-stream")
async def stream_voice_input(
    websocket: WebSocket,
    session_id: int,
    version: int,
    target: VoiceInputTarget = "SELF_EXPLANATION",
    target_id: str | None = Query(default=None, alias="targetId"),
) -> None:
    requested_protocols = websocket.headers.get("Sec-WebSocket-Protocol", "")
    await websocket.accept(subprotocol="bearer" if requested_protocols else None)
    database_session = websocket.app.state.database_session_factory()
    request_id = websocket.headers.get("X-Request-ID") or new_correlation_id()
    trace_id = websocket.headers.get("X-Trace-ID") or request_id
    trace_tokens = bind_trace_context(
        request_id=request_id,
        trace_id=trace_id,
        span_id=new_correlation_id(),
        session_id=session_id,
    )
    capture = None
    service: RealtimeASRService | None = None
    try:
        repository = SessionRepository(database_session)
        session = repository.get(session_id)
        try:
            current_user = get_current_user(websocket, database_session)
        except HTTPException as error:
            await reject_voice_stream(websocket, str(error.detail))
            return
        if session is None or session.user_id != current_user.id:
            await reject_voice_stream(websocket, f"会话不存在：{session_id}")
            return
        if session.status != STATUS_IN_PROGRESS:
            await reject_voice_stream(websocket, f"当前会话状态不允许语音输入：{session.status}")
            return
        if session.version != version:
            await reject_voice_stream(
                websocket, f"会话版本已变化，当前版本为 {session.version}，请刷新后重试"
            )
            return
        allowed_stages = {
            "SELF_EXPLANATION": frozenset({FLOW_STAGE_CAPTURING_INPUT}),
            "SELF_EXPLANATION_STEP": frozenset({FLOW_STAGE_CAPTURING_INPUT}),
            "SELF_EXPLANATION_EXPLAIN": frozenset({FLOW_STAGE_CAPTURING_INPUT}),
            "GUIDED_ANSWER": frozenset({FLOW_STAGE_WAIT_GUIDED_ANSWERS}),
            "DOUBT": STUDENT_INTERRUPTION_FLOW_STAGES,
            "APPEAL": STUDENT_INTERRUPTION_FLOW_STAGES,
        }[target]
        if session.flow_stage not in allowed_stages:
            await reject_voice_stream(
                websocket, f"当前流程阶段不能进行语音输入：{session.flow_stage}"
            )
            return
        if target in {"SELF_EXPLANATION_STEP", "SELF_EXPLANATION_EXPLAIN"}:
            if target_id is not None:
                await reject_voice_stream(websocket, "单步自讲语音输入不能携带 targetId")
                return
            if session.current_step_id is None:
                await reject_voice_stream(websocket, "当前自讲草稿不存在")
                return
            try:
                repository.get_editable_step(session, session.current_step_id)
            except ValueError as error:
                await reject_voice_stream(websocket, str(error))
                return
        elif target == "GUIDED_ANSWER":
            support_event = repository.get_pending_guided_support(session.id)
            guided_question_ids = (
                {
                    str(item["id"])
                    for item in support_event.guided_questions or []
                    if "id" in item
                }
                if support_event is not None
                else set()
            )
            if target_id is None or target_id not in guided_question_ids:
                await reject_voice_stream(websocket, "语音输入对应的子问题不存在或已经提交")
                return
        elif target_id is not None:
            await reject_voice_stream(websocket, "当前语音输入目标不能携带 targetId")
            return
        if (
            target == "APPEAL"
            and repository.get_latest_valid_evaluation(session.id) is None
            and repository.get_latest_valid_support(session.id) is None
        ):
            await reject_voice_stream(websocket, "尚未获得可申诉的 AI 回复")
            return

        settings = websocket.app.state.settings
        audio_storage = AudioStorage(settings)
        capture = audio_storage.start_capture(session.id)
        service, attempt_number, started_at = await start_realtime_asr(
            settings=settings,
            repository=repository,
            session=session,
            start_attempt_number=1,
        )
        if service is None:
            capture.delete()
            repository.record_asr_stream_failure(
                session=session, trigger_type="ASR_STREAM_RETRY_EXHAUSTED"
            )
            await reject_voice_stream(websocket, "实时语音识别服务暂时不可用，请重新录音")
            return

        await websocket.send_json(
            {
                "type": "ready",
                "sampleRateHz": settings.asr_sample_rate_hz,
                "channels": settings.asr_channels,
                "frameDurationMs": settings.asr_frame_duration_ms,
            }
        )
        final_transcripts: list[str] = []
        raw_responses: list[dict[str, object]] = []
        receive_task = asyncio.create_task(websocket.receive())
        event_task = asyncio.create_task(service.events.get())
        while True:
            done, _ = await asyncio.wait(
                {receive_task, event_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if receive_task in done:
                message = receive_task.result()
                receive_task = asyncio.create_task(websocket.receive())
                if message["type"] == "websocket.disconnect":
                    return
                if message.get("bytes") is not None:
                    frame = message["bytes"]
                    try:
                        capture.append(frame)
                        service.send_audio_frame(frame)
                    except (ASRServiceError, AudioStorageError) as error:
                        repository.record_external_call(
                            session=session,
                            call_type="ASR",
                            attempt_number=attempt_number,
                            transport_status="ERROR",
                            duration_ms=round((time.perf_counter() - started_at) * 1000),
                            provider=settings.asr_provider,
                            model=settings.asr_model,
                            error_type="ASR_SERVICE_ERROR",
                            error_message=str(error),
                        )
                        capture.delete()
                        repository.record_asr_stream_failure(
                            session=session, trigger_type="ASR_STREAM_FAILED"
                        )
                        await reject_voice_stream(websocket, "实时语音识别失败，请重新录音")
                        return
                elif message.get("text") is not None:
                    try:
                        control_message = json.loads(message["text"])
                    except json.JSONDecodeError:
                        await reject_voice_stream(websocket, "语音控制消息不是合法 JSON")
                        return
                    if control_message.get("type") != "stop":
                        await reject_voice_stream(websocket, "不支持的语音控制消息")
                        return
                    receive_task.cancel()
                    finished_service = service
                    await asyncio.to_thread(finished_service.stop)
                    service = None
                    if event_task.done():
                        event = event_task.result()
                        if event.event_type == "final_transcript" and event.text is not None:
                            final_transcripts.append(event.text)
                            if event.raw_response is not None:
                                raw_responses.append(event.raw_response)
                    else:
                        event_task.cancel()
                    while not finished_service.events.empty():
                        event = finished_service.events.get_nowait()
                        if event.event_type == "final_transcript" and event.text is not None:
                            final_transcripts.append(event.text)
                            if event.raw_response is not None:
                                raw_responses.append(event.raw_response)
                    asr_transcript = "".join(final_transcripts).strip()
                    if not asr_transcript:
                        repository.record_external_call(
                            session=session,
                            call_type="ASR",
                            attempt_number=attempt_number,
                            transport_status="ERROR",
                            duration_ms=round((time.perf_counter() - started_at) * 1000),
                            provider=settings.asr_provider,
                            model=settings.asr_model,
                            error_type="ASR_SERVICE_ERROR",
                            error_message="实时 ASR 未返回有效转写文本",
                        )
                        capture.delete()
                        repository.record_asr_stream_failure(
                            session=session, trigger_type="ASR_STREAM_FAILED"
                        )
                        await reject_voice_stream(websocket, "未获得有效转写，请重新录音")
                        return
                    try:
                        completed_session, attempt = repository.complete_voice_transcription(
                            session=session,
                            capture=capture,
                            audio_storage=audio_storage,
                            asr_transcript=asr_transcript,
                            voice_target=target,
                            voice_target_id=target_id,
                            expected_version=version,
                        )
                    except (SessionVersionConflict, ValueError) as error:
                        capture.delete()
                        await reject_voice_stream(websocket, str(error))
                        return
                    repository.record_external_call(
                        session=completed_session,
                        call_type="ASR",
                        attempt_number=attempt_number,
                        transport_status="SUCCESS",
                        duration_ms=round((time.perf_counter() - started_at) * 1000),
                        provider=settings.asr_provider,
                        model=settings.asr_model,
                        raw_response=json.dumps(raw_responses, ensure_ascii=False),
                    )
                    await websocket.send_json(
                        {
                            "type": "completed",
                            "attemptId": attempt.id,
                            "asrTranscript": asr_transcript,
                            "version": completed_session.version,
                        }
                    )
                    await websocket.close()
                    return
            if event_task in done:
                event: ASRStreamEvent = event_task.result()
                event_task = asyncio.create_task(service.events.get())
                if event.event_type in {"partial_transcript", "final_transcript"}:
                    if event.event_type == "final_transcript" and event.text is not None:
                        final_transcripts.append(event.text)
                        if event.raw_response is not None:
                            raw_responses.append(event.raw_response)
                    await websocket.send_json({"type": event.event_type, "text": event.text})
                elif event.event_type == "error":
                    repository.record_external_call(
                        session=session,
                        call_type="ASR",
                        attempt_number=attempt_number,
                        transport_status="ERROR",
                        duration_ms=round((time.perf_counter() - started_at) * 1000),
                        provider=settings.asr_provider,
                        model=settings.asr_model,
                        error_type=event.error_type,
                        error_message=event.error_message,
                    )
                    await asyncio.to_thread(service.stop)
                    event_task.cancel()
                    capture.delete()
                    repository.record_asr_stream_failure(
                        session=session, trigger_type="ASR_STREAM_FAILED"
                    )
                    await reject_voice_stream(websocket, "实时语音识别连接已中断，请重新录音")
                    return
    except WebSocketDisconnect:
        return
    except AudioStorageError as error:
        if capture is not None:
            capture.delete()
        await reject_voice_stream(websocket, str(error))
    finally:
        if service is not None:
            try:
                await asyncio.to_thread(service.stop)
            except ASRServiceError:
                logger.exception("关闭实时 ASR 失败", extra={"operation": "close_realtime_asr"})
        reset_trace_context(trace_tokens)
        database_session.close()


def apply_support_request_output(
    *,
    repository: SessionRepository,
    session: Session,
    main_draft: str,
    doubt_text: str | None,
    output,
    settings,
) -> Session:
    if output.action == "REFUSE_FULL_SOLUTION":
        return repository.record_full_solution_refusal(
            session=session,
            main_draft=main_draft,
            doubt_text=doubt_text,
            content=output.content,
        )
    if output.action == "SIMPLE_DOUBT_ANSWER":
        return repository.record_direct_help(
            session=session,
            main_draft=main_draft,
            doubt_text=doubt_text,
            content=output.content,
            support_kind="SIMPLE_DOUBT",
            settings=settings,
        )
    if output.action != "GUIDED_QUESTIONS":
        raise RuntimeError(f"不支持的教学支持动作：{output.action}")
    return repository.record_guided_questions(
        session=session,
        main_draft=main_draft,
        doubt_text=doubt_text,
        content=output.content,
        questions=output.questions,
        settings=settings,
    )
