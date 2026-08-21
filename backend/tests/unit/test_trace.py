from datetime import UTC, datetime, timedelta

import pytest

from app.models.session_event import SessionEvent
from app.services.trace import TraceService

BASE_TIME = datetime(2026, 8, 20, 10, 20, tzinfo=UTC)


def event(
    seq: int,
    event_type: str,
    *,
    run_id: str,
    parent_event_id: str | None = None,
    occurred_offset: int | None = None,
) -> SessionEvent:
    return SessionEvent(
        id=seq + 1,
        session_id=42,
        seq=seq,
        event_id=f"evt_{seq}",
        run_id=run_id,
        parent_event_id=parent_event_id,
        event_type=event_type,
        occurred_at=BASE_TIME + timedelta(seconds=occurred_offset or seq),
        data={},
    )


def test_trace_uses_only_parent_event_id_and_keeps_runs_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        event(1, "user.message", run_id="run_1", occurred_offset=30),
        event(
            2,
            "model.requested",
            run_id="run_1",
            parent_event_id="evt_1",
            occurred_offset=10,
        ),
        event(
            3,
            "model.responded",
            run_id="run_1",
            parent_event_id="evt_2",
            occurred_offset=5,
        ),
        event(4, "user.message", run_id="run_1"),
        event(5, "user.message", run_id="run_2", parent_event_id="evt_1"),
    ]
    service = TraceService(database_session=None)  # type: ignore[arg-type]
    monkeypatch.setattr(service.event_store, "list_events", lambda session_id: events)

    trace = service.build_trace(42, "run_1")

    assert [root.seq for root in trace.roots] == [1, 4]
    assert trace.roots[0].children[0].seq == 2
    assert trace.roots[0].children[0].children[0].seq == 3
    assert all(node.seq != 5 for node in trace.roots)


def test_trace_treats_parent_outside_selected_run_as_query_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        event(1, "user.message", run_id="run_1"),
        event(2, "state.changed", run_id="run_2", parent_event_id="evt_1"),
    ]
    service = TraceService(database_session=None)  # type: ignore[arg-type]
    monkeypatch.setattr(service.event_store, "list_events", lambda session_id: events)

    trace = service.build_trace(42, "run_2")

    assert [root.seq for root in trace.roots] == [2]


def test_trace_rejects_empty_run_id() -> None:
    service = TraceService(database_session=None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="run_id"):
        service.build_trace(42, "")
