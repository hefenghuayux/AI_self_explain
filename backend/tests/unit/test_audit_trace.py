import json
from datetime import UTC, datetime
from pathlib import Path

from app.models.explanation_attempt import ExplanationAttempt
from app.models.student_submission import StudentSubmission
from app.schemas.audit import (
    SessionTraceResponse,
    SessionTraceSummaryResponse,
    TraceProducerResponse,
)
from app.services.audit_trace import AuditTraceService


def test_event_serializes_success_without_inapplicable_fields() -> None:
    service = AuditTraceService(database_session=None, export_dir=Path("unused"))

    event = service._event(
        session_id=15,
        event_id="submission-13",
        occurred_at=datetime(2026, 8, 10, 3, 12, 39),
        event_name="student.explanation.submitted",
        request_id="request-1",
        operation={"name": "SELF_EXPLANATION", "kind": "STUDENT_INPUT"},
        result=service._result("SUCCESS"),
        data={},
        references={},
    )

    payload = event.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert event.occurred_at == datetime(2026, 8, 10, 3, 12, 39, tzinfo=UTC)
    assert payload["occurredAt"] == "2026-08-10T03:12:39Z"
    assert payload["correlation"] == {"sessionId": 15, "requestId": "request-1"}
    assert payload["result"] == {"status": "SUCCESS"}
    assert "schemaVersion" not in payload
    assert "source" not in payload
    assert "privacy" not in payload


def test_error_result_uses_nested_error_object() -> None:
    service = AuditTraceService(database_session=None, export_dir=Path("unused"))

    result = service._result(
        "ERROR",
        duration_ms=30001,
        error_type="AI_TIMEOUT",
        error_message="AI 请求超时",
    )

    assert result.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "status": "ERROR",
        "durationMs": 30001,
        "error": {"type": "AI_TIMEOUT", "message": "AI 请求超时"},
    }


def test_jsonl_export_replaces_old_schema_with_v3_envelopes(tmp_path: Path) -> None:
    service = AuditTraceService(database_session=None, export_dir=tmp_path)
    event = service._event(
        session_id=7,
        event_id="state-transition-1",
        occurred_at=datetime(2026, 8, 10, tzinfo=UTC),
        event_name="session.created",
        request_id=None,
        operation={"name": "CREATE_SESSION", "kind": "STATE_TRANSITION"},
        result=service._result("SUCCESS"),
        data={},
        references={"stateTransitionEventId": 1},
    )
    trace = SessionTraceResponse(
        schema_version="3.0",
        producer=TraceProducerResponse(service="ai-self-explain-backend", version="0.1.0"),
        session_id=7,
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
        summary=SessionTraceSummaryResponse(
            status="IN_PROGRESS",
            flow_stage="WAIT_INITIAL_CHOICE",
            round=1,
            event_count=1,
            error_count=0,
            external_call_count=0,
        ),
        events=[event],
    )
    jsonl_path = tmp_path / "trace.jsonl"
    jsonl_path.write_text('{"schemaVersion":"2.0","eventId":"old"}\n', encoding="utf-8")

    service._write_jsonl(jsonl_path, trace)

    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    envelope = json.loads(lines[0])
    assert envelope["schemaVersion"] == "3.0"
    assert envelope["producer"] == {
        "service": "ai-self-explain-backend",
        "version": "0.1.0",
    }
    assert envelope["sessionId"] == 7
    assert envelope["event"]["eventId"] == "state-transition-1"
    assert "schemaVersion" not in envelope["event"]
    assert "source" not in envelope["event"]
    assert not jsonl_path.with_suffix(".jsonl.tmp").exists()


def test_non_self_explanation_submission_keeps_generic_event_name() -> None:
    service = AuditTraceService(database_session=None, export_dir=Path("unused"))
    submission = StudentSubmission(
        id=21,
        session_id=7,
        request_id="guided-request",
        submission_type="GUIDED_ANSWER",
        content="子问题回答",
        context={"supportEventId": 9, "round": 1},
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    events = service._submission_events(7, [submission], {}, {})

    assert len(events) == 1
    assert events[0].event_name == "student.input.submitted"
    assert events[0].correlation.request_id == "guided-request"
    assert events[0].references == {"studentSubmissionId": 21}


def test_voice_transcription_is_removed_after_self_explanation_submission() -> None:
    service = AuditTraceService(database_session=None, export_dir=Path("unused"))
    attempt = ExplanationAttempt(
        id=13,
        session_id=7,
        round=1,
        input_mode="VOICE",
        voice_target="SELF_EXPLANATION",
        voice_target_id=None,
        audio_file_id=5,
        asr_transcript="语音草稿",
        confirmed_text=None,
        confirmed_at=None,
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    before_submission = service._attempt_events(7, [attempt], {13: "voice-request"}, set())
    after_submission = service._attempt_events(7, [attempt], {13: "voice-request"}, {13})

    assert [event.event_name for event in before_submission] == ["voice.transcription.completed"]
    assert after_submission == []
