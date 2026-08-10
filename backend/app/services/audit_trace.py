import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from app.models.ai_evaluation import AIEvaluation
from app.models.audio_file import AudioFile
from app.models.explanation_attempt import ExplanationAttempt
from app.models.external_call_record import ExternalCallRecord
from app.models.session import Session
from app.models.state_transition_event import StateTransitionEvent
from app.models.student_submission import StudentSubmission
from app.models.support_event import SupportEvent
from app.schemas.audit import (
    AuditExportResponse,
    SessionTraceResponse,
    SessionTraceSummaryResponse,
    TraceCorrelationResponse,
    TraceErrorResponse,
    TraceEventResponse,
    TraceExportEnvelope,
    TraceProducerResponse,
    TraceResultResponse,
)

TRACE_SCHEMA_VERSION = "3.0"
TRACE_PRODUCER = TraceProducerResponse(service="ai-self-explain-backend", version="0.1.0")
_export_lock = threading.Lock()


class AuditTraceService:
    def __init__(self, database_session: DatabaseSession, export_dir: Path) -> None:
        self.database_session = database_session
        self.export_dir = export_dir

    def build_session_trace(self, session_id: int) -> SessionTraceResponse:
        session = self.database_session.get(Session, session_id)
        if session is None:
            raise ValueError(f"会话不存在：{session_id}")

        state_events = self._records(StateTransitionEvent, session_id)
        external_calls = self._records(ExternalCallRecord, session_id)
        attempts = self._records(ExplanationAttempt, session_id)
        evaluations = self._records(AIEvaluation, session_id)
        submissions = self._records(StudentSubmission, session_id)
        supports = self._records(SupportEvent, session_id)
        audio_files = self._records(AudioFile, session_id)

        attempt_request_ids = {
            event.related_attempt_id: event.request_id
            for event in state_events
            if event.related_attempt_id is not None and event.request_id is not None
        }
        evaluation_request_ids = {
            event.related_evaluation_id: event.request_id
            for event in state_events
            if event.related_evaluation_id is not None and event.request_id is not None
        }
        audio_request_ids = {
            attempt.audio_file_id: attempt_request_ids.get(attempt.id)
            for attempt in attempts
            if attempt.audio_file_id is not None
        }
        attempts_by_id = {attempt.id: attempt for attempt in attempts}
        submitted_self_explanation_attempt_ids = {
            attempt_id
            for submission in submissions
            if submission.submission_type == "SELF_EXPLANATION"
            and isinstance((attempt_id := submission.context.get("attemptId")), int)
        }

        events: list[TraceEventResponse] = []
        events.extend(self._state_events(session_id, state_events))
        events.extend(self._external_call_events(session_id, external_calls))
        events.extend(
            self._attempt_events(
                session_id,
                attempts,
                attempt_request_ids,
                submitted_self_explanation_attempt_ids,
            )
        )
        events.extend(self._evaluation_events(session_id, evaluations, evaluation_request_ids))
        events.extend(
            self._submission_events(session_id, submissions, attempts_by_id, attempt_request_ids)
        )
        events.extend(self._support_events(session_id, supports, evaluation_request_ids))
        events.extend(self._audio_events(session_id, audio_files, audio_request_ids))
        events.sort(key=lambda event: (event.occurred_at, event.event_id))
        for sequence, event in enumerate(events, start=1):
            event.sequence = sequence

        return SessionTraceResponse(
            schema_version=TRACE_SCHEMA_VERSION,
            producer=TRACE_PRODUCER,
            session_id=session.id,
            generated_at=datetime.now(UTC),
            summary=SessionTraceSummaryResponse(
                status=session.status,
                flow_stage=session.flow_stage,
                round=session.round,
                event_count=len(events),
                error_count=sum(event.result.status == "ERROR" for event in events),
                external_call_count=len(external_calls),
            ),
            events=events,
        )

    def export_session(self, session_id: int) -> AuditExportResponse:
        trace = self.build_session_trace(session_id)
        session_dir = self.export_dir / str(session_id)
        jsonl_path = session_dir / "trace.jsonl"
        markdown_path = session_dir / "audit.md"
        with _export_lock:
            session_dir.mkdir(parents=True, exist_ok=True)
            self._write_jsonl(jsonl_path, trace)
            self._write_markdown(markdown_path, trace)
        return AuditExportResponse(
            session_id=session_id,
            jsonl_path=str(jsonl_path.resolve()),
            markdown_path=str(markdown_path.resolve()),
            event_count=len(trace.events),
        )

    def _records(self, model, session_id: int) -> list:
        return list(
            self.database_session.scalars(
                select(model)
                .where(model.session_id == session_id)
                .order_by(model.created_at, model.id)
            )
        )

    def _state_events(
        self, session_id: int, records: list[StateTransitionEvent]
    ) -> list[TraceEventResponse]:
        events = []
        for record in records:
            data: dict[str, object] = {
                "fromStatus": record.from_status,
                "toStatus": record.to_status,
                "toFlowStage": record.to_flow_stage,
                "beforeSnapshot": record.before_snapshot,
                "afterSnapshot": record.after_snapshot,
            }
            if record.from_flow_stage is not None:
                data["fromFlowStage"] = record.from_flow_stage
            references: dict[str, object] = {"stateTransitionEventId": record.id}
            if record.related_attempt_id is not None:
                references["attemptId"] = record.related_attempt_id
            if record.related_evaluation_id is not None:
                references["evaluationId"] = record.related_evaluation_id
            if record.related_support_event_id is not None:
                references["supportEventId"] = record.related_support_event_id
            events.append(
                self._event(
                    session_id=session_id,
                    event_id=f"state-transition-{record.id}",
                    occurred_at=record.created_at,
                    event_name=(
                        "session.created"
                        if record.trigger_type == "CREATE_SESSION"
                        else "state.transitioned"
                    ),
                    request_id=record.request_id,
                    operation={"name": record.trigger_type, "kind": "STATE_TRANSITION"},
                    result=self._result("SUCCESS"),
                    data=data,
                    references=references,
                )
            )
        return events

    def _external_call_events(
        self, session_id: int, records: list[ExternalCallRecord]
    ) -> list[TraceEventResponse]:
        events = []
        for record in records:
            target = "asr" if record.call_type == "ASR" else "ai"
            status = "ERROR" if record.status == "ERROR" else "SUCCESS"
            data: dict[str, object] = {
                "provider": record.provider,
                "model": record.model,
            }
            raw_response = _text_fingerprint(record.raw_response)
            redacted_fields = None
            if raw_response is not None:
                data["rawResponse"] = raw_response
                redacted_fields = ["rawResponse"]
            events.append(
                self._event(
                    session_id=session_id,
                    event_id=f"external-call-{record.id}",
                    occurred_at=record.created_at,
                    event_name=f"{target}.call.{'failed' if status == 'ERROR' else 'completed'}",
                    request_id=record.request_id,
                    severity="ERROR" if status == "ERROR" else "INFO",
                    operation={
                        "name": record.call_type,
                        "kind": "EXTERNAL_CALL",
                        "attemptNumber": record.attempt_number,
                    },
                    result=self._result(
                        status,
                        duration_ms=record.duration_ms,
                        error_type=record.error_type,
                        error_message=record.error_message,
                    ),
                    data=data,
                    references={"externalCallRecordId": record.id},
                    redacted_fields=redacted_fields,
                )
            )
        return events

    def _attempt_events(
        self,
        session_id: int,
        records: list[ExplanationAttempt],
        request_ids: dict[int, str | None],
        submitted_attempt_ids: set[int],
    ) -> list[TraceEventResponse]:
        events = []
        for record in records:
            if record.input_mode != "VOICE" or record.id in submitted_attempt_ids:
                continue
            data: dict[str, object] = {"round": record.round}
            if record.voice_target is not None:
                data["voiceTarget"] = record.voice_target
            if record.voice_target_id is not None:
                data["voiceTargetId"] = record.voice_target_id
            asr_transcript = _text_fingerprint(record.asr_transcript)
            if asr_transcript is not None:
                data["asrTranscript"] = asr_transcript
            confirmed_text = _text_fingerprint(record.confirmed_text)
            if confirmed_text is not None:
                data["confirmedText"] = confirmed_text
            if record.confirmed_at is not None:
                data["confirmedAt"] = record.confirmed_at
            references: dict[str, object] = {"attemptId": record.id}
            if record.audio_file_id is not None:
                references["audioFileId"] = record.audio_file_id
            redacted_fields = [
                field_name
                for field_name, value in (
                    ("asrTranscript", asr_transcript),
                    ("confirmedText", confirmed_text),
                )
                if value is not None
            ]
            events.append(
                self._event(
                    session_id=session_id,
                    event_id=f"attempt-{record.id}",
                    occurred_at=record.created_at,
                    event_name="voice.transcription.completed",
                    request_id=request_ids.get(record.id),
                    operation={"name": "TRANSCRIBE_VOICE", "kind": "VOICE"},
                    result=self._result("SUCCESS"),
                    data=data,
                    references=references,
                    redacted_fields=redacted_fields or None,
                )
            )
        return events

    def _evaluation_events(
        self,
        session_id: int,
        records: list[AIEvaluation],
        request_ids: dict[int, str | None],
    ) -> list[TraceEventResponse]:
        events = []
        for record in records:
            valid = record.validation_status == "VALID"
            data: dict[str, object] = {
                "promptVersion": record.prompt_version,
                "provider": record.model_provider,
                "model": record.model_name,
                "validationStatus": record.validation_status,
            }
            for field_name, value in (
                ("correctness", record.correctness),
                ("completeness", record.completeness),
                ("coveredPoints", record.covered_points),
                ("missingPoints", record.missing_points),
                ("errorEvidence", record.error_evidence),
                ("confidence", record.confidence),
                ("needHumanReason", record.need_human_reason),
            ):
                if value is not None:
                    data[field_name] = value
            raw_response = _text_fingerprint(record.raw_response)
            if raw_response is not None:
                data["rawResponse"] = raw_response
            events.append(
                self._event(
                    session_id=session_id,
                    event_id=f"evaluation-{record.id}",
                    occurred_at=record.created_at,
                    event_name="ai.output.validated" if valid else "ai.output.validation_failed",
                    request_id=request_ids.get(record.id),
                    severity="INFO" if valid else "WARNING",
                    operation={"name": "VALIDATE_AI_EVALUATION", "kind": "AI_EVALUATION"},
                    result=self._result(
                        "SUCCESS" if valid else "ERROR",
                        duration_ms=record.request_duration_ms,
                        error_type=None if valid else "AI_SCHEMA_ERROR",
                        error_message=None if valid else "; ".join(record.validation_errors),
                    ),
                    data=data,
                    references={"evaluationId": record.id, "attemptId": record.attempt_id},
                    redacted_fields=["rawResponse"] if raw_response is not None else None,
                )
            )
        return events

    def _submission_events(
        self,
        session_id: int,
        records: list[StudentSubmission],
        attempts_by_id: dict[int, ExplanationAttempt],
        request_ids: dict[int, str | None],
    ) -> list[TraceEventResponse]:
        events = []
        for record in records:
            attempt_id = record.context.get("attemptId")
            attempt = attempts_by_id.get(attempt_id) if isinstance(attempt_id, int) else None
            references: dict[str, object] = {"studentSubmissionId": record.id}
            if attempt is not None:
                references["attemptId"] = attempt.id
                if attempt.audio_file_id is not None:
                    references["audioFileId"] = attempt.audio_file_id
            content = _text_fingerprint(record.content)
            if content is None:
                raise ValueError(f"学生提交 {record.id} 缺少内容")
            if record.submission_type == "SELF_EXPLANATION":
                data: dict[str, object] = {"content": content}
                round_number = record.context.get(
                    "round", attempt.round if attempt is not None else None
                )
                if round_number is not None:
                    data["round"] = round_number
                input_mode = (
                    attempt.input_mode
                    if attempt is not None
                    else record.context.get("inputMode")
                )
                if input_mode is not None:
                    data["inputMode"] = input_mode
                if attempt is not None and attempt.confirmed_at is not None:
                    data["confirmedAt"] = attempt.confirmed_at
                event_name = "student.explanation.submitted"
            else:
                data = {"content": content, "context": record.context}
                event_name = "student.input.submitted"
            events.append(
                self._event(
                    session_id=session_id,
                    event_id=f"submission-{record.id}",
                    occurred_at=record.created_at,
                    event_name=event_name,
                    request_id=(
                        record.request_id
                        or (request_ids.get(attempt_id) if isinstance(attempt_id, int) else None)
                    ),
                    operation={"name": record.submission_type, "kind": "STUDENT_INPUT"},
                    result=self._result("SUCCESS"),
                    data=data,
                    references=references,
                    redacted_fields=["content"],
                )
            )
        return events

    def _support_events(
        self,
        session_id: int,
        records: list[SupportEvent],
        request_ids: dict[int, str | None],
    ) -> list[TraceEventResponse]:
        events = []
        for record in records:
            data: dict[str, object] = {
                "round": record.round,
                "status": record.status,
                "content": record.content,
            }
            for field_name, value in (
                ("guidedQuestions", record.guided_questions),
                ("guidedAnswers", record.guided_answers),
                ("followUpContent", record.follow_up_content),
            ):
                if value is not None:
                    data[field_name] = value
            main_draft = _text_fingerprint(record.main_draft)
            doubt_text = _text_fingerprint(record.doubt_text)
            if main_draft is not None:
                data["mainDraft"] = main_draft
            if doubt_text is not None:
                data["doubtText"] = doubt_text
            references: dict[str, object] = {"supportEventId": record.id}
            if record.evaluation_id is not None:
                references["evaluationId"] = record.evaluation_id
            redacted_fields = [
                field_name
                for field_name, value in (
                    ("mainDraft", main_draft),
                    ("doubtText", doubt_text),
                )
                if value is not None
            ]
            events.append(
                self._event(
                    session_id=session_id,
                    event_id=f"support-{record.id}",
                    occurred_at=record.created_at,
                    event_name="support.generated",
                    request_id=record.request_id or request_ids.get(record.evaluation_id),
                    operation={"name": record.support_type, "kind": record.support_kind},
                    result=self._result("SUCCESS"),
                    data=data,
                    references=references,
                    redacted_fields=redacted_fields or None,
                )
            )
        return events

    def _audio_events(
        self,
        session_id: int,
        records: list[AudioFile],
        request_ids: dict[int, str | None],
    ) -> list[TraceEventResponse]:
        return [
            self._event(
                session_id=session_id,
                event_id=f"audio-{record.id}",
                occurred_at=record.created_at,
                event_name="audio.persisted",
                request_id=request_ids.get(record.id),
                operation={"name": "STORE_AUDIO", "kind": "FILE_STORAGE"},
                result=self._result("SUCCESS"),
                data={
                    "contentType": record.content_type,
                    "sizeBytes": record.size_bytes,
                    "sha256": record.sha256,
                },
                references={"audioFileId": record.id},
                redacted_fields=["relativePath"],
            )
            for record in records
        ]

    def _event(
        self,
        *,
        session_id: int,
        event_id: str,
        occurred_at: datetime,
        event_name: str,
        request_id: str | None,
        operation: dict[str, object],
        result: TraceResultResponse,
        data: dict[str, object],
        references: dict[str, object],
        severity: str = "INFO",
        redacted_fields: list[str] | None = None,
    ) -> TraceEventResponse:
        # SQLite 返回的 DateTime 可能丢失时区信息；数据库默认时间按 UTC 保存，
        # 这里统一补齐并转换为 UTC，确保接口序列化后带有 `Z`，前端不会误当成本地时间。
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        else:
            occurred_at = occurred_at.astimezone(UTC)
        return TraceEventResponse(
            event_id=event_id,
            sequence=0,
            occurred_at=occurred_at,
            event_name=event_name,
            severity=severity,
            correlation=TraceCorrelationResponse(
                session_id=session_id,
                request_id=request_id,
            ),
            operation=operation,
            result=result,
            data=data,
            references=references,
            privacy=({"redactedFields": redacted_fields} if redacted_fields else None),
        )

    def _result(
        self,
        status: str,
        *,
        duration_ms: int | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> TraceResultResponse:
        error = None
        if status == "ERROR":
            if error_type is None or error_message is None:
                raise ValueError("失败结果必须提供 error_type 和 error_message")
            error = TraceErrorResponse(type=error_type, message=error_message)
        return TraceResultResponse(status=status, duration_ms=duration_ms, error=error)

    def _write_jsonl(self, jsonl_path: Path, trace: SessionTraceResponse) -> None:
        temporary_path = jsonl_path.with_suffix(".jsonl.tmp")
        with temporary_path.open("w", encoding="utf-8", newline="\n") as trace_file:
            for event in trace.events:
                envelope = TraceExportEnvelope(
                    schema_version=trace.schema_version,
                    producer=trace.producer,
                    session_id=trace.session_id,
                    event=event,
                )
                trace_file.write(
                    json.dumps(
                        envelope.model_dump(mode="json", by_alias=True, exclude_none=True),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
            trace_file.flush()

        for line_number, line in enumerate(
            temporary_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            try:
                TraceExportEnvelope.model_validate_json(line)
            except ValueError as error:
                raise ValueError(
                    f"JSONL 临时文件第 {line_number} 行格式无效：{temporary_path}"
                ) from error
        temporary_path.replace(jsonl_path)

    def _write_markdown(self, markdown_path: Path, trace: SessionTraceResponse) -> None:
        lines = [
            f"# 会话审计报告：session-{trace.session_id}",
            "",
            "## 会话概览",
            "",
            f"- 会话 ID：{trace.session_id}",
            f"- 当前状态：{trace.summary.status}",
            f"- 当前阶段：{trace.summary.flow_stage}",
            f"- 当前轮次：{trace.summary.round}",
            f"- 事件数量：{trace.summary.event_count}",
            f"- 外部调用：{trace.summary.external_call_count}",
            f"- 错误数量：{trace.summary.error_count}",
            "",
            "## 执行链路",
            "",
            "| 序号 | 时间 | 事件 | 状态 |",
            "| ---: | --- | --- | --- |",
        ]
        for event in trace.events:
            lines.append(
                f"| {event.sequence} | {event.occurred_at.isoformat()} | "
                f"{event.event_name} | {event.result.status} |"
            )
        lines.extend(["", "## 事件明细", ""])
        for event in trace.events:
            event_json = json.dumps(
                event.model_dump(mode="json", by_alias=True, exclude_none=True),
                ensure_ascii=False,
                indent=2,
            )
            lines.extend(
                [
                    f"### {event.sequence}. {event.event_name}",
                    "",
                    "```json",
                    event_json,
                    "```",
                    "",
                ]
            )
        lines.extend(
            [
                "## 脱敏说明",
                "",
                "学生原始输入、ASR 原始文本、完整模型原始响应和本地音频路径不直接写入本报告。",
                "报告仅保存长度、SHA-256、必要的业务结果及数据库记录引用。",
                "",
            ]
        )
        temporary_path = markdown_path.with_suffix(".md.tmp")
        temporary_path.write_text("\n".join(lines), encoding="utf-8")
        temporary_path.replace(markdown_path)


def _text_fingerprint(value: str | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "characterCount": len(value),
        "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
    }
