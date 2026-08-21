from copy import deepcopy
from datetime import UTC, datetime

import pytest

from app.models.session_event import SessionEvent
from app.services.surface import SurfaceService


def event(seq: int, event_type: str, data: dict[str, object]) -> SessionEvent:
    return SessionEvent(
        id=seq + 1,
        session_id=42,
        seq=seq,
        event_id=f"evt_{seq}",
        run_id="run_1" if seq else None,
        parent_event_id=None,
        event_type=event_type,
        occurred_at=datetime(2026, 8, 20, 10, 20, seq, tzinfo=UTC),
        data=data,
    )


def test_surface_folds_only_model_visible_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        event(0, "session.started", {}),
        event(1, "user.message", {"text": "我的答案是 2", "inputType": "text"}),
        event(
            2,
            "context.added",
            {"kind": "question", "source": "question:12", "content": "计算 1 + 1"},
        ),
        event(
            3,
            "model.requested",
            {
                "provider": "test-ai",
                "model": "test-model",
                "messages": [{"role": "user", "content": "实际请求"}],
                "surfaceSeq": 2,
            },
        ),
        event(4, "model.responded", {"output": {"answer": 2}, "validation": "valid"}),
        event(5, "state.changed", {"from": "A", "to": "B", "reason": "completed"}),
    ]
    original_data = deepcopy([item.data for item in events])
    service = SurfaceService(database_session=None)  # type: ignore[arg-type]
    monkeypatch.setattr(service.event_store, "list_events", lambda session_id: events)

    surface = service.build_surface(42)

    assert surface.model_dump(mode="json", by_alias=True) == {
        "sessionId": 42,
        "asOfSeq": 5,
        "messages": [{"seq": 1, "role": "user", "content": "我的答案是 2"}],
        "contexts": [
            {
                "seq": 2,
                "kind": "question",
                "source": "question:12",
                "content": "计算 1 + 1",
            }
        ],
    }
    assert [item.data for item in events] == original_data


def test_surface_rebuilds_history_as_of_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        event(0, "session.started", {}),
        event(1, "user.message", {"text": "第一次", "inputType": "text"}),
        event(2, "user.message", {"text": "第二次", "inputType": "text"}),
    ]
    service = SurfaceService(database_session=None)  # type: ignore[arg-type]
    monkeypatch.setattr(service.event_store, "list_events", lambda session_id: events)

    surface = service.build_surface(42, as_of_seq=1)

    assert surface.as_of_seq == 1
    assert [message.content for message in surface.messages] == ["第一次"]


def test_surface_rejects_negative_sequence() -> None:
    service = SurfaceService(database_session=None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="as_of_seq"):
        service.build_surface(42, as_of_seq=-1)
