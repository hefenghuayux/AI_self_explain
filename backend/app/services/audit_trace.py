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
    TraceEventResponse,
    TraceResultResponse,
)

TRACE_SCHEMA_VERSION = "1.0"
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

        events: list[TraceEventResponse] = []
        events.extend(self._state_events(session_id, state_events))
        events.extend(self._external_call_events(session_id, external_calls))
        events.extend(self._attempt_events(session_id, attempts, attempt_request_ids))
        events.extend(self._evaluation_events(session_id, evaluations, evaluation_request_ids))
        events.extend(self._submission_events(session_id, submissions, attempt_request_ids))
        events.extend(self._support_events(session_id, supports, evaluation_request_ids))
        events.extend(self._audio_events(session_id, audio_files, audio_request_ids))
        events.sort(key=lambda event: (event.occurred_at, event.event_id))
        for sequence, event in enumerate(events, start=1):
            event.sequence = sequence

        return SessionTraceResponse(
            schema_version=TRACE_SCHEMA_VERSION,
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
            existing_event_ids = self._read_existing_event_ids(jsonl_path)
            with jsonl_path.open("a", encoding="utf-8", newline="\n") as trace_file:
                for event in trace.events:
                    if event.event_id in existing_event_ids:
                        continue
                    trace_file.write(
                        json.dumps(
                            event.model_dump(mode="json", by_alias=True),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
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
        return [
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
                data={
                    "fromStatus": record.from_status,
                    "toStatus": record.to_status,
                    "fromFlowStage": record.from_flow_stage,
                    "toFlowStage": record.to_flow_stage,
                    "beforeSnapshot": record.before_snapshot,
                    "afterSnapshot": record.after_snapshot,
                },
                references={
                    "stateTransitionEventId": record.id,
                    "attemptId": record.related_attempt_id,
                    "evaluationId": record.related_evaluation_id,
                },
            )
            for record in records
        ]

    def _external_call_events(
        self, session_id: int, records: list[ExternalCallRecord]
    ) -> list[TraceEventResponse]:
        events = []
        for record in records:
            target = "asr" if record.call_type == "ASR" else "ai"
            status = "ERROR" if record.status == "ERROR" else "SUCCESS"
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
                    data={
                        "provider": record.provider,
                        "model": record.model,
                        "rawResponse": _text_fingerprint(record.raw_response),
                    },
                    references={"externalCallRecordId": record.id},
                    redacted_fields=["rawResponse"],
                )
            )
        return events

    def _attempt_events(
        self,
        session_id: int,
        records: list[ExplanationAttempt],
        request_ids: dict[int, str | None],
    ) -> list[TraceEventResponse]:
        return [
            self._event(
                session_id=session_id,
                event_id=f"attempt-{record.id}",
                occurred_at=record.created_at,
                event_name=(
                    "voice.capture.completed"
                    if record.input_mode == "VOICE"
                    else "student.input.confirmed"
                ),
                request_id=request_ids.get(record.id),
                operation={"name": "CAPTURE_INPUT", "kind": record.input_mode},
                result=self._result("SUCCESS"),
                data={
                    "round": record.round,
                    "voiceTarget": record.voice_target,
                    "voiceTargetId": record.voice_target_id,
                    "asrTranscript": _text_fingerprint(record.asr_transcript),
                    "confirmedText": _text_fingerprint(record.confirmed_text),
                    "confirmedAt": record.confirmed_at,
                },
                references={"attemptId": record.id, "audioFileId": record.audio_file_id},
                redacted_fields=["asrTranscript", "confirmedText"],
            )
            for record in records
        ]

    def _evaluation_events(
        self,
        session_id: int,
        records: list[AIEvaluation],
        request_ids: dict[int, str | None],
    ) -> list[TraceEventResponse]:
        events = []
        for record in records:
            valid = record.validation_status == "VALID"
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
                    data={
                        "correctness": record.correctness,
                        "completeness": record.completeness,
                        "coveredPoints": record.covered_points,
                        "missingPoints": record.missing_points,
                        "errorEvidence": record.error_evidence,
                        "feedback": record.feedback,
                        "confidence": record.confidence,
                        "nextAction": record.next_action,
                        "needHumanReason": record.need_human_reason,
                        "promptVersion": record.prompt_version,
                        "provider": record.model_provider,
                        "model": record.model_name,
                        "validationStatus": record.validation_status,
                        "rawResponse": _text_fingerprint(record.raw_response),
                    },
                    references={"evaluationId": record.id, "attemptId": record.attempt_id},
                    redacted_fields=["rawResponse"],
                )
            )
        return events

    def _submission_events(
        self,
        session_id: int,
        records: list[StudentSubmission],
        request_ids: dict[int, str | None],
    ) -> list[TraceEventResponse]:
        events = []
        for record in records:
            attempt_id = record.context.get("attemptId")
            events.append(
                self._event(
                    session_id=session_id,
                    event_id=f"submission-{record.id}",
                    occurred_at=record.created_at,
                    event_name="student.input.submitted",
                    request_id=(
                        request_ids.get(attempt_id) if isinstance(attempt_id, int) else None
                    ),
                    operation={"name": record.submission_type, "kind": "STUDENT_INPUT"},
                    result=self._result("SUCCESS"),
                    data={"content": _text_fingerprint(record.content), "context": record.context},
                    references={"studentSubmissionId": record.id, "attemptId": attempt_id},
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
        return [
            self._event(
                session_id=session_id,
                event_id=f"support-{record.id}",
                occurred_at=record.created_at,
                event_name="support.generated",
                request_id=request_ids.get(record.evaluation_id),
                operation={"name": record.support_type, "kind": record.support_kind},
                result=self._result("SUCCESS" if record.status == "VALID" else "ERROR"),
                data={
                    "round": record.round,
                    "status": record.status,
                    "content": record.content,
                    "guidedQuestions": record.guided_questions,
                    "guidedAnswers": record.guided_answers,
                    "followUpContent": record.follow_up_content,
                    "mainDraft": _text_fingerprint(record.main_draft),
                    "doubtText": _text_fingerprint(record.doubt_text),
                },
                references={"supportEventId": record.id, "evaluationId": record.evaluation_id},
                redacted_fields=["mainDraft", "doubtText"],
            )
            for record in records
        ]

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
        trace_id = request_id or f"session-{session_id}"
        return TraceEventResponse(
            schema_version=TRACE_SCHEMA_VERSION,
            event_id=event_id,
            sequence=0,
            occurred_at=occurred_at,
            event_name=event_name,
            severity=severity,
            source={"service": "ai-self-explain-backend", "module": "audit_trace"},
            correlation=TraceCorrelationResponse(
                session_id=session_id,
                request_id=request_id,
                trace_id=trace_id,
                span_id=event_id,
                parent_span_id=None,
            ),
            operation=operation,
            result=result,
            data=data,
            references=references,
            privacy={"redactedFields": redacted_fields or []},
        )

    def _result(
        self,
        status: str,
        *,
        duration_ms: int | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> TraceResultResponse:
        return TraceResultResponse(
            status=status,
            duration_ms=duration_ms,
            error_type=error_type,
            error_message=error_message,
        )

    def _read_existing_event_ids(self, jsonl_path: Path) -> set[str]:
        if not jsonl_path.exists():
            return set()
        event_ids = set()
        for line_number, line in enumerate(
            jsonl_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            try:
                event_id = json.loads(line)["eventId"]
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                raise ValueError(f"JSONL 第 {line_number} 行格式无效：{jsonl_path}") from error
            event_ids.add(str(event_id))
        return event_ids

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
            "| 序号 | 时间 | 事件 | 状态 | Trace ID |",
            "| ---: | --- | --- | --- | --- |",
        ]
        for event in trace.events:
            lines.append(
                f"| {event.sequence} | {event.occurred_at.isoformat()} | "
                f"{event.event_name} | {event.result.status} | {event.correlation.trace_id} |"
            )
        lines.extend(["", "## 事件明细", ""])
        for event in trace.events:
            event_json = json.dumps(
                event.model_dump(mode="json", by_alias=True),
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
