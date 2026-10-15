"""Answer a frozen student question without entering the learning state machine."""

import json
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select

from app.models.ai_run import AIRun
from app.models.external_call_record import ExternalCallRecord
from app.models.question import Question
from app.models.session import Session
from app.schemas.model_request_snapshot import ModelRequestSnapshot
from app.services.ai_evaluation import AIModelClient, AIServiceUnavailableError, AITransportError
from app.services.ai_run import current_run
from app.services.ai_stream import (
    current_stream,
    stream_failed,
    stream_validated,
    terminal_snapshot,
)
from app.services.ai_support import _model_request, _question_context
from app.services.context_history import build_shared_history
from app.services.context_runtime import current_context
from app.services.event_store import EventStore
from app.services.session_event_log import SessionEventLog

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "answer_doubt.md"


class IndependentDoubtInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doubt_text: str = Field(alias="doubtText", min_length=1)
    main_draft: str = Field(default="", alias="mainDraft")

    @field_validator("doubt_text")
    @classmethod
    def require_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请先输入疑问")
        return value


class IndependentDoubtAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def require_answer(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("疑问回答不能为空")
        return value


def accept_doubt(db, session, run_id: str, payload: IndependentDoubtInput, settings) -> None:
    """Persist the accepted input and its history before starting background work."""
    question = db.get(Question, session.question_id)
    history = build_shared_history(db, session)
    request = _model_request(
        purpose="INDEPENDENT_DOUBT",
        prompt_version=settings.prompt_version,
        task_instructions=PROMPT_PATH.read_text(encoding="utf-8"),
        question_context=_question_context(question),
        session_context={"taskType": "INDEPENDENT_DOUBT", "round": session.round},
        user_input=payload.model_dump(by_alias=True),
        validation_errors=[],
        model=settings.ai_model,
        reasoning_effort=settings.ai_reasoning_effort,
        progress_context=history,
    )
    request.blocks.memory_context = history
    request.privacy.contains_memory = bool(history.get("summary"))
    request.transport.extra_body["max_tokens"] = settings.ai_max_output_tokens
    db.add(AIRun(
        id=run_id,
        session_id=session.id,
        base_version=session.version,
        status="ACTIVE",
        snapshot={
            "operation": "independent-doubt",
            "input": payload.model_dump(by_alias=True),
            "round": session.round,
            "request": request.database_value(),
        },
        checkpoints={},
    ))
    db.commit()


def answer_doubt(app, session_id: int, run_id: str) -> dict[str, str]:
    """Keep database transactions short: the model call owns no session row or runtime lock."""
    run_token = current_run.set(None)
    context_token = current_context.set(None)
    try:
        return _answer_doubt(app, session_id, run_id)
    finally:
        current_context.reset(context_token)
        current_run.reset(run_token)


def _answer_doubt(app, session_id: int, run_id: str) -> dict[str, str]:
    factory = app.state.database_session_factory
    settings = app.state.settings
    with factory() as db:
        record = db.get(AIRun, run_id)
        frozen = dict(record.snapshot)
    request = ModelRequestSnapshot.model_validate(frozen["request"])
    client = AIModelClient(settings, app.state.ai_http_client)
    external_attempt = 0
    for schema_attempt in range(settings.ai_schema_max_retries + 1):
        for transport_attempt in range(settings.ai_transport_max_retries + 1):
            external_attempt += 1
            with factory() as db:
                log = SessionEventLog(db)
                requested = log.append_model_requested(
                    session_id=session_id, run_id=run_id, request=request,
                    provider=settings.ai_provider,
                    parent_event_id=log.latest_event_id(session_id, run_id),
                )
                requested_id = requested.event_id
            try:
                response = client.evaluate(request)
            except AITransportError as error:
                with factory() as db:
                    db.add(ExternalCallRecord(
                        session_id=session_id, request_id=run_id,
                        call_type=request.purpose, provider=settings.ai_provider,
                        model=request.transport.model, attempt_number=external_attempt,
                        transport_status="ERROR", validation_status="NOT_RUN",
                        duration_ms=error.duration_ms, error_type=error.error_type,
                        error_message=str(error), raw_response=error.raw_response,
                        request_snapshot=request.database_value(),
                    ))
                    SessionEventLog(db).append_model_failed(
                        session_id=session_id, run_id=run_id,
                        error_type=error.error_type, message=str(error),
                        duration_ms=error.duration_ms, parent_event_id=requested_id,
                    )
                # A concurrent doubt must never compact or overwrite shared history.
                if error.error_type == "CONTEXT_WINDOW_EXCEEDED" or (
                    transport_attempt == settings.ai_transport_max_retries
                ):
                    raise AIServiceUnavailableError() from error
                time.sleep(settings.ai_retry_backoff_seconds[transport_attempt])
                continue
            break

        try:
            output = IndependentDoubtAnswer.model_validate_json(response.content)
            validation_errors = []
        except (ValidationError, ValueError) as error:
            output = None
            validation_errors = (
                [entry["msg"] for entry in error.errors()]
                if isinstance(error, ValidationError) else [str(error)]
            )
        with factory() as db:
            db.add(ExternalCallRecord(
                session_id=session_id, request_id=run_id,
                call_type=request.purpose, provider=settings.ai_provider,
                model=request.transport.model, attempt_number=external_attempt,
                transport_status="SUCCESS",
                validation_status="VALID" if output else "INVALID",
                validation_errors=validation_errors,
                duration_ms=response.duration_ms, raw_response=response.raw_response,
                request_snapshot=request.database_value(),
            ))
            SessionEventLog(db).append_model_responded(
                session_id=session_id, run_id=run_id,
                response_content=response.content,
                validation="valid" if output else "invalid",
                duration_ms=response.duration_ms, parent_event_id=requested_id,
                raw_response=response.raw_response,
            )
        if output is not None:
            stream_validated(request.purpose)
            result = output.model_dump()
            stream = current_stream.get()
            snapshot = stream.registry.snapshot(run_id)
            # Answer and successful terminal checkpoint commit together. A restart
            # cannot publish a failed answer that is already in shared history.
            with factory() as db:
                completion_round = db.scalar(
                    select(Session.round).where(Session.id == session_id).with_for_update()
                )
                EventStore(db).append(
                    session_id=session_id, event_type="context.added", run_id=run_id,
                    parent_event_id=requested_id,
                    data={
                        "kind": "memory", "source": "independent_doubt",
                        "content": {
                            "round": completion_round,
                            "question": frozen["input"]["doubtText"],
                            "answer": output.content,
                        },
                    },
                )
                record = db.scalar(select(AIRun).where(AIRun.id == run_id).with_for_update())
                record.status = "COMPLETED"
                record.checkpoints = {
                    **record.checkpoints, "stream": terminal_snapshot(snapshot, result=result),
                }
                db.commit()
            return result
        stream_failed(request.purpose)
        if schema_attempt == settings.ai_schema_max_retries:
            raise AIServiceUnavailableError()
        request.blocks.retry_context = {"validationErrors": validation_errors}
        task_data = {**request.blocks.user_input, **request.blocks.session_context,
                     "validationErrors": validation_errors}
        request.transport.messages[-1].content = json.dumps(task_data, ensure_ascii=False)
    raise RuntimeError("独立答疑重试未产生结果")
