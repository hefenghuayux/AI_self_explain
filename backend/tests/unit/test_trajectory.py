from datetime import UTC, datetime, timedelta

import pytest

from app.models.session_event import SessionEvent
from app.schemas.session_projection import ModelCallStep, StateChangeStep, UserInputStep
from app.services.trajectory import TrajectoryService

BASE_TIME = datetime(2026, 8, 20, 10, 20, tzinfo=UTC)


def event(
    seq: int,
    event_type: str,
    data: dict[str, object],
    *,
    run_id: str,
    parent_event_id: str | None = None,
) -> SessionEvent:
    return SessionEvent(
        id=seq + 1,
        session_id=42,
        seq=seq,
        event_id=f"evt_{seq}",
        run_id=run_id,
        parent_event_id=parent_event_id,
        event_type=event_type,
        occurred_at=BASE_TIME + timedelta(seconds=seq),
        data=data,
    )


def test_trajectory_groups_runs_and_builds_only_three_step_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        event(1, "user.message", {"text": "第一次", "inputType": "text"}, run_id="run_1"),
        event(
            2,
            "model.requested",
            {
                "provider": "test-ai",
                "model": "test-model",
                "messages": [{"role": "user", "content": "评价"}],
                "surfaceSeq": 1,
            },
            run_id="run_1",
            parent_event_id="evt_1",
        ),
        event(
            3,
            "model.responded",
            {"output": {}, "validation": "invalid", "durationMs": 1200},
            run_id="run_1",
            parent_event_id="evt_2",
        ),
        event(
            4,
            "state.changed",
            {"from": "EVALUATING", "to": "WAIT_STUDENT_ACTION", "reason": "completed"},
            run_id="run_1",
            parent_event_id="evt_3",
        ),
        event(5, "user.message", {"text": "第二次", "inputType": "text"}, run_id="run_2"),
    ]
    service = TrajectoryService(database_session=None)  # type: ignore[arg-type]
    monkeypatch.setattr(service.event_store, "list_events", lambda session_id: events)

    trajectory = service.build_trajectory(42)

    assert [run.run_id for run in trajectory.runs] == ["run_1", "run_2"]
    assert [type(step) for step in trajectory.runs[0].steps] == [
        UserInputStep,
        ModelCallStep,
        StateChangeStep,
    ]
    model_step = trajectory.runs[0].steps[1]
    assert isinstance(model_step, ModelCallStep)
    assert model_step.status == "success"
    assert model_step.result_seq == 3
    assert model_step.duration_ms == 1200
    state_step = trajectory.runs[0].steps[2]
    assert isinstance(state_step, StateChangeStep)
    assert state_step.from_ == "EVALUATING"
    assert state_step.to == "WAIT_STUDENT_ACTION"


def test_trajectory_marks_model_failure_and_pending_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        event(
            1,
            "model.requested",
            {
                "provider": "test-ai",
                "model": "test-model",
                "messages": [{"role": "user", "content": "请求一"}],
                "surfaceSeq": 0,
            },
            run_id="run_1",
        ),
        event(
            2,
            "model.failed",
            {"errorType": "TIMEOUT", "message": "超时", "durationMs": 30000},
            run_id="run_1",
            parent_event_id="evt_1",
        ),
        event(
            3,
            "model.requested",
            {
                "provider": "test-ai",
                "model": "test-model",
                "messages": [{"role": "user", "content": "请求二"}],
                "surfaceSeq": 2,
            },
            run_id="run_1",
        ),
    ]
    service = TrajectoryService(database_session=None)  # type: ignore[arg-type]
    monkeypatch.setattr(service.event_store, "list_events", lambda session_id: events)

    trajectory = service.build_trajectory(42)

    first, second = trajectory.runs[0].steps
    assert isinstance(first, ModelCallStep)
    assert (first.status, first.result_seq, first.duration_ms) == ("failed", 2, 30000)
    assert isinstance(second, ModelCallStep)
    assert (second.status, second.result_seq) == ("pending", None)
