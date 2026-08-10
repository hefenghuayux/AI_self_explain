import json
from datetime import UTC, datetime
from pathlib import Path

from app.models.explanation_attempt import ExplanationAttempt
from app.models.external_call_record import ExternalCallRecord
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


def test_ai_external_call_projects_request_snapshot_and_validation_event() -> None:
    service = AuditTraceService(database_session=None, export_dir=Path("unused"))
    snapshot = {
        "schemaVersion": "1.0",
        "purpose": "AI_EVALUATION",
        "promptVersion": "evaluation-v1",
        "blocks": {
            "systemInstructions": "评价规则",
            "questionContext": {"questionContent": "1+1"},
            "sessionContext": {},
            "userInput": {"confirmedText": "等于 2"},
            "retryContext": {"validationErrors": []},
        },
        "transport": {
            "model": "test-model",
            "messages": [{"role": "user", "content": "评价提示词"}],
            "response_format": {"type": "json_object"},
        },
        "privacy": {
            "containsStudentContent": True,
            "containsAnswerMaterial": True,
            "containsMemory": False,
        },
    }
    record = ExternalCallRecord(
        id=3,
        session_id=7,
        request_id="request-3",
        call_type="AI_EVALUATION",
        provider="test-provider",
        model="test-model",
        attempt_number=1,
        transport_status="SUCCESS",
        validation_status="VALID",
        validation_errors=[],
        request_snapshot=snapshot,
        duration_ms=12,
        raw_response='{"choices":[]}',
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    events = service._external_call_events(7, [record], {})

    assert [event.event_name for event in events] == [
        "ai.call.completed",
        "ai.output.validated",
    ]
    assert events[0].data["requestSnapshot"] == snapshot
    assert events[0].data["requestSnapshotAvailability"] == "AVAILABLE"
    assert events[0].privacy == {
        "containsStudentContent": True,
        "containsAnswerMaterial": True,
        "containsMemory": False,
        "redactedFields": ["rawResponse"],
    }


def test_external_call_distinguishes_historical_ai_and_asr_snapshot_availability() -> None:
    service = AuditTraceService(database_session=None, export_dir=Path("unused"))
    common = {
        "session_id": 7,
        "request_id": None,
        "provider": "test-provider",
        "model": "test-model",
        "attempt_number": 1,
        "transport_status": "SUCCESS",
        "validation_status": "UNKNOWN",
        "validation_errors": None,
        "request_snapshot": None,
        "duration_ms": 12,
        "created_at": datetime(2026, 8, 10, tzinfo=UTC),
    }
    historical_ai = ExternalCallRecord(id=4, call_type="AI_EVALUATION", **common)
    asr = ExternalCallRecord(id=5, call_type="ASR", **common)

    events = service._external_call_events(7, [historical_ai, asr], {})

    assert events[0].data["requestSnapshotAvailability"] == "NOT_RECORDED"
    assert events[1].data["requestSnapshotAvailability"] == "NOT_APPLICABLE"
    assert all("requestSnapshot" not in event.data for event in events)


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


def test_business_trace_groups_submission_and_ai_events_by_references() -> None:
    service = AuditTraceService(database_session=None, export_dir=Path("unused"))
    occurred_at = datetime(2026, 8, 10, tzinfo=UTC)
    submission = service._event(
        session_id=7,
        event_id="submission-1",
        occurred_at=occurred_at,
        event_name="student.explanation.submitted",
        request_id="request-1",
        operation={"name": "SELF_EXPLANATION", "kind": "STUDENT_INPUT"},
        result=service._result("SUCCESS"),
        data={"round": 1, "inputMode": "TEXT"},
        references={"attemptId": 11},
    )
    ai_call = service._event(
        session_id=7,
        event_id="external-call-2",
        occurred_at=occurred_at,
        event_name="ai.call.completed",
        request_id="request-1",
        operation={"name": "AI_EVALUATION", "kind": "EXTERNAL_CALL"},
        result=service._result("SUCCESS", duration_ms=20),
        data={},
        references={"externalCallRecordId": 2},
    )
    ai_output = service._event(
        session_id=7,
        event_id="external-call-2-validation",
        occurred_at=occurred_at,
        event_name="ai.output.validated",
        request_id="request-1",
        operation={"name": "AI_EVALUATION", "kind": "OUTPUT_VALIDATION"},
        result=service._result("SUCCESS"),
        data={"correctness": "CORRECT", "completeness": "COMPLETE"},
        references={"externalCallRecordId": 2, "evaluationId": 3, "attemptId": 11},
    )
    transition = service._event(
        session_id=7,
        event_id="state-transition-4",
        occurred_at=occurred_at,
        event_name="state.transitioned",
        request_id="request-1",
        operation={"name": "APPLY_AI_EVALUATION", "kind": "STATE_TRANSITION"},
        result=service._result("SUCCESS"),
        data={},
        references={"evaluationId": 3, "attemptId": 11},
    )
    for sequence, event in enumerate(
        [submission, ai_call, ai_output, transition], start=1
    ):
        event.sequence = sequence
    trace = SessionTraceResponse(
        schema_version="3.0",
        producer=TraceProducerResponse(service="test", version="1"),
        session_id=7,
        generated_at=occurred_at,
        summary=SessionTraceSummaryResponse(
            status="COMPLETED",
            flow_stage="WAIT_STUDENT_ACTION",
            round=1,
            event_count=4,
            error_count=0,
            external_call_count=1,
        ),
        events=[submission, ai_call, ai_output, transition],
    )

    business_trace = service._business_trace_from_trace(trace)

    assert [step.kind for step in business_trace.steps] == ["SUBMISSION", "AI"]
    assert business_trace.steps[1].event_ids == [
        "external-call-2",
        "external-call-2-validation",
        "state-transition-4",
    ]
    assert business_trace.steps[1].duration_ms == 20
