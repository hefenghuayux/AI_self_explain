from datetime import UTC, datetime
from pathlib import Path

from app.schemas.audit import TraceResultResponse
from app.services.audit_trace import AuditTraceService


def test_event_serializes_naive_database_timestamp_as_utc() -> None:
    service = AuditTraceService(database_session=None, export_dir=Path("unused"))

    event = service._event(
        session_id=15,
        event_id="attempt-13",
        occurred_at=datetime(2026, 8, 10, 3, 12, 39),
        event_name="student.input.confirmed",
        request_id="request-1",
        operation={"name": "CAPTURE_INPUT", "kind": "TEXT"},
        result=TraceResultResponse(
            status="SUCCESS",
            duration_ms=None,
            error_type=None,
            error_message=None,
        ),
        data={},
        references={},
    )

    assert event.occurred_at == datetime(2026, 8, 10, 3, 12, 39, tzinfo=UTC)
    assert event.model_dump(mode="json", by_alias=True)["occurredAt"] == "2026-08-10T03:12:39Z"
