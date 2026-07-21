import asyncio
import json
import logging
import time

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status

from app.api.questions import DatabaseSession
from app.models.question import Question
from app.models.session import Session
from app.repositories.sessions import SessionRepository
from app.rules.session_lifecycle import (
    FLOW_STAGE_CAPTURING_INPUT,
    FLOW_STAGE_CONFIRMING_TEXT,
    FLOW_STAGE_SHOWING_FULL_SOLUTION,
    FLOW_STAGE_WAIT_GUIDED_ANSWERS,
    FLOW_STAGE_WAIT_INITIAL_CHOICE,
    FLOW_STAGE_WAIT_STUDENT_ACTION,
    STATUS_IN_PROGRESS,
    STATUS_PAUSED,
    TERMINAL_STATUSES,
    can_pause,
)
from app.schemas.session import (
    AppealInput,
    CreateSessionInput,
    DoubtRequestInput,
    EvaluationRetryInput,
    GuidedAnswersInput,
    HelpRequestInput,
    InitialChoiceInput,
    LearningTimelineItemResponse,
    SessionResponse,
    SolutionUnderstandingInput,
    StudentActionInput,
    TextAttemptInput,
    VoiceTranscriptConfirmationInput,
)
from app.schemas.support import SupportEventResponse
from app.services.ai_evaluation import AIEvaluationService
from app.services.ai_support import AISupportService
from app.services.audio_storage import AudioStorage, AudioStorageError
from app.services.realtime_asr import ASRServiceError, ASRStreamEvent, RealtimeASRService

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


def validate_pauseable(session: Session) -> None:
    if session.status in TERMINAL_STATUSES:
        reject_operation(f"终态会话不能暂停：{session.status}")
    if session.status != STATUS_IN_PROGRESS:
        reject_operation(f"当前会话状态不允许暂停：{session.status}")
    if not can_pause(session.flow_stage):
        reject_operation(f"当前流程阶段不能暂停：{session.flow_stage}")


def to_session_response(repository: SessionRepository, session: Session) -> SessionResponse:
    latest_support = repository.get_latest_valid_support(session.id)
    pending_voice_attempt = repository.get_pending_voice_attempt(session.id)
    return SessionResponse.model_validate(session).model_copy(
        update={
            "latest_evaluation": repository.get_latest_valid_evaluation(session.id),
            "latest_support": (
                SupportEventResponse.model_validate(latest_support)
                if latest_support is not None
                else None
            ),
            "pending_voice_attempt": pending_voice_attempt,
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


@router.post("/{session_id}/pause", response_model=SessionResponse)
def pause_session(
    session_id: int, action_input: StudentActionInput, database_session: DatabaseSession
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id)
    validate_version(session, action_input.version)
    validate_pauseable(session)
    return to_session_response(repository, repository.pause(session))


@router.post("/{session_id}/resume", response_model=SessionResponse)
def resume_session(
    session_id: int, action_input: StudentActionInput, database_session: DatabaseSession
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id)
    validate_version(session, action_input.version)
    if session.status != STATUS_PAUSED:
        reject_operation(f"当前会话状态不允许恢复：{session.status}")
    return to_session_response(repository, repository.resume(session))


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
    evaluated_session = AIEvaluationService(database_session, request.app.state.settings).evaluate(
        question=database_session.get(Question, session.question_id),
        session=session,
        attempt=attempt,
    )
    return to_session_response(repository, evaluated_session)


@router.post("/{session_id}/voice-attempts/confirm", response_model=SessionResponse)
def confirm_voice_attempt(
    session_id: int,
    attempt_input: VoiceTranscriptConfirmationInput,
    database_session: DatabaseSession,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id)
    validate_in_progress(session)
    validate_version(session, attempt_input.version)
    if session.flow_stage != FLOW_STAGE_CONFIRMING_TEXT:
        reject_operation(f"当前流程阶段不能确认语音转写：{session.flow_stage}")
    attempt = repository.get_pending_voice_attempt(session.id)
    if attempt is None or attempt.id != attempt_input.attempt_id:
        reject_operation("待确认的语音转写不存在或已变化")
    confirmed_session, confirmed_attempt = repository.confirm_voice_attempt(
        session=session,
        attempt=attempt,
        confirmed_text=attempt_input.confirmed_text,
    )
    question = database_session.get(Question, confirmed_session.question_id)
    if question is None:
        raise RuntimeError(
            f"会话 {confirmed_session.id} 关联题目不存在：{confirmed_session.question_id}"
        )
    evaluated_session = AIEvaluationService(database_session, request.app.state.settings).evaluate(
        question=question, session=confirmed_session, attempt=confirmed_attempt
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
    action_input: HelpRequestInput,
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
    support_service = AISupportService(database_session, request.app.state.settings)
    output = support_service.generate_request(
        question=question,
        session=session,
        main_draft=action_input.main_draft,
        doubt_text=None,
        force_current_step=False,
    )
    if output is None:
        return to_session_response(repository, session)
    generated_session = apply_support_request_output(
        repository=repository,
        support_service=support_service,
        question=question,
        session=session,
        main_draft=action_input.main_draft,
        doubt_text=None,
        output=output,
        settings=request.app.state.settings,
    )
    return to_session_response(repository, generated_session)


@router.post("/{session_id}/ask-doubt", response_model=SessionResponse)
def ask_doubt(
    session_id: int,
    action_input: DoubtRequestInput,
    database_session: DatabaseSession,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id)
    validate_in_progress(session)
    validate_version(session, action_input.version)
    if session.flow_stage != FLOW_STAGE_WAIT_STUDENT_ACTION:
        reject_operation(f"当前流程阶段不能提出疑问：{session.flow_stage}")
    question = database_session.get(Question, session.question_id)
    if question is None:
        raise RuntimeError(f"会话 {session.id} 关联题目不存在：{session.question_id}")
    support_service = AISupportService(database_session, request.app.state.settings)
    output = support_service.generate_request(
        question=question,
        session=session,
        main_draft=action_input.main_draft,
        doubt_text=action_input.doubt_text,
        force_current_step=False,
    )
    if output is None:
        return to_session_response(repository, session)
    generated_session = apply_support_request_output(
        repository=repository,
        support_service=support_service,
        question=question,
        session=session,
        main_draft=action_input.main_draft,
        doubt_text=action_input.doubt_text,
        output=output,
        settings=request.app.state.settings,
    )
    return to_session_response(repository, generated_session)


@router.post("/{session_id}/guided-answers", response_model=SessionResponse)
def submit_guided_answers(
    session_id: int,
    action_input: GuidedAnswersInput,
    database_session: DatabaseSession,
    request: Request,
) -> SessionResponse:
    repository = SessionRepository(database_session)
    session = get_session_or_404(repository, session_id)
    validate_in_progress(session)
    validate_version(session, action_input.version)
    if session.flow_stage != FLOW_STAGE_WAIT_GUIDED_ANSWERS:
        reject_operation(f"当前流程阶段不能提交子问题答案：{session.flow_stage}")
    support_event = repository.get_pending_guided_support(session.id)
    if support_event is None:
        raise RuntimeError(f"会话 {session.id} 缺少待回答的子问题支持事件")
    question = database_session.get(Question, session.question_id)
    if question is None:
        raise RuntimeError(f"会话 {session.id} 关联题目不存在：{session.question_id}")
    support_service = AISupportService(database_session, request.app.state.settings)
    assessment = support_service.assess_guided_answers(
        question=question,
        session=session,
        support_event=support_event,
        answers=action_input.answers,
    )
    if assessment is None:
        return to_session_response(repository, session)
    updated_session = repository.record_guided_answers(
        session=session,
        support_event=support_event,
        answers=action_input.answers,
        follow_up_content=assessment.content,
    )
    return to_session_response(repository, updated_session)


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
    if attempt is None or attempt.confirmed_text is None:
        raise RuntimeError(f"会话 {session.id} 缺少可重新评价的确认文本")
    session = repository.begin_ai_evaluation(session, attempt)
    question = database_session.get(Question, session.question_id)
    if question is None:
        raise RuntimeError(f"会话 {session.id} 关联题目不存在：{session.question_id}")
    evaluated_session = AIEvaluationService(database_session, request.app.state.settings).evaluate(
        question=question, session=session, attempt=attempt
    )
    return to_session_response(repository, evaluated_session)


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
                status="ERROR",
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
async def stream_voice_input(websocket: WebSocket, session_id: int, version: int) -> None:
    await websocket.accept()
    database_session = websocket.app.state.database_session_factory()
    capture = None
    service: RealtimeASRService | None = None
    try:
        repository = SessionRepository(database_session)
        session = repository.get(session_id)
        if session is None:
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
        if session.flow_stage != FLOW_STAGE_CAPTURING_INPUT:
            await reject_voice_stream(
                websocket, f"当前流程阶段不能进行语音输入：{session.flow_stage}"
            )
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
                            status="ERROR",
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
                            status="ERROR",
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
                    completed_session, attempt = repository.complete_voice_transcription(
                        session=session,
                        capture=capture,
                        audio_storage=audio_storage,
                        asr_transcript=asr_transcript,
                    )
                    repository.record_external_call(
                        session=completed_session,
                        call_type="ASR",
                        attempt_number=attempt_number,
                        status="SUCCESS",
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
                        status="ERROR",
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
        database_session.close()


def apply_support_request_output(
    *,
    repository: SessionRepository,
    support_service: AISupportService,
    question: Question,
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
    if output.action == "CURRENT_STEP_ANSWER":
        return repository.record_direct_help(
            session=session,
            main_draft=main_draft,
            doubt_text=doubt_text,
            content=output.content,
            support_kind="CURRENT_STEP",
            settings=settings,
        )
    if output.action != "GUIDED_QUESTIONS":
        raise RuntimeError(f"不支持的教学支持动作：{output.action}")
    force_current_step = repository.record_help_progress(
        session=session,
        main_draft=main_draft,
        covered_points=output.covered_points,
        settings=settings,
    )
    if force_current_step:
        step_output = support_service.generate_request(
            question=question,
            session=session,
            main_draft=main_draft,
            doubt_text=doubt_text,
            force_current_step=True,
        )
        if step_output is None:
            return session
        if step_output.action != "CURRENT_STEP_ANSWER":
            raise RuntimeError("AI 未按确定性规则生成当前步骤答案")
        return repository.record_direct_help(
            session=session,
            main_draft=main_draft,
            doubt_text=doubt_text,
            content=step_output.content,
            support_kind="CURRENT_STEP",
            settings=settings,
        )
    return repository.record_guided_questions(
        session=session,
        main_draft=main_draft,
        doubt_text=doubt_text,
        content=output.content,
        questions=output.questions,
        settings=settings,
    )
