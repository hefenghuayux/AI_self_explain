from datetime import UTC, datetime, timedelta

import pytest

from app.models.session_event import SessionEvent
from app.schemas.session_projection import (
    ModelCallStep,
    StateChangeStep,
    TrajectoryRecord,
    UserInputStep,
)
from app.services.trajectory import TrajectoryService

BASE_TIME = datetime(2026, 8, 20, 10, 20, tzinfo=UTC)


def event(
    seq: int,
    event_type: str,
    data: dict[str, object],
    *,
    run_id: str | None,
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


def build_service(monkeypatch: pytest.MonkeyPatch, events: list[SessionEvent]) -> TrajectoryService:
    service = TrajectoryService(database_session=None)  # type: ignore[arg-type]
    monkeypatch.setattr(service.event_store, "list_events", lambda session_id: events)
    return service


def records_by_seq(records: tuple[TrajectoryRecord, ...]) -> dict[int, TrajectoryRecord]:
    return {record.event_seq: record for record in records}


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
            {
                "output": {},
                "rawContent": "{}",
                "validation": "invalid",
                "durationMs": 1200,
            },
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
    trajectory = build_service(monkeypatch, events).build_trajectory(42)

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
    trajectory = build_service(monkeypatch, events).build_trajectory(42)

    first, second = trajectory.runs[0].steps
    assert isinstance(first, ModelCallStep)
    assert (first.status, first.result_seq, first.duration_ms) == ("failed", 2, 30000)
    assert isinstance(second, ModelCallStep)
    assert (second.status, second.result_seq) == ("pending", None)


def test_trajectory_builds_one_record_per_event_with_kind_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        event(0, "session.started", {}, run_id=None),
        event(1, "user.message", {"text": "1 加 1 等于 2。", "inputType": "text"}, run_id="run_1"),
        event(
            2,
            "context.added",
            {"kind": "question", "source": "question:1", "content": "计算 1 + 1。"},
            run_id="run_1",
            parent_event_id="evt_1",
        ),
        event(
            3,
            "model.requested",
            {
                "provider": "test-ai",
                "model": "test-model",
                "messages": [{"role": "user", "content": "请评价"}],
                "surfaceSeq": 2,
            },
            run_id="run_1",
            parent_event_id="evt_2",
        ),
        event(
            4,
            "model.responded",
            {
                "output": {"correctness": "CORRECT", "confidence": 1, "missingPoints": []},
                "rawContent": '{"correctness": "CORRECT"}',
                "validation": "valid",
                "durationMs": 3,
                "inputTokens": 120,
                "outputTokens": 30,
            },
            run_id="run_1",
            parent_event_id="evt_3",
        ),
        event(
            5,
            "model.failed",
            {"errorType": "TIMEOUT", "message": "超时", "durationMs": 30000},
            run_id="run_2",
            parent_event_id="evt_missing",
        ),
        event(
            6,
            "state.changed",
            {"from": "AI_EVALUATING", "to": "WAIT_STUDENT_ACTION", "reason": "done"},
            run_id="run_1",
            parent_event_id="evt_4",
        ),
        event(
            7,
            "model.requested",
            {
                "provider": "test-ai",
                "model": "test-model",
                "messages": [{"role": "user", "content": "未返回"}],
                "surfaceSeq": 6,
            },
            run_id="run_2",
        ),
    ]
    trajectory = build_service(monkeypatch, events).build_trajectory(42)

    assert [record.index for record in trajectory.events] == list(range(1, 9))
    records = records_by_seq(trajectory.events)
    assert [record.kind for record in trajectory.events] == [
        "session",
        "user",
        "context",
        "model_request",
        "model_response",
        "model_error",
        "state_change",
        "model_request",
    ]
    assert records[1].summary == "1 加 1 等于 2。"
    assert records[1].detail.user is not None
    assert records[1].detail.user.input_type == "text"
    assert records[2].summary == "question · question:1"
    assert records[2].detail.context is not None
    assert records[3].summary == "test-model · 1 条消息 · surfaceSeq #2"
    assert records[3].status == "complete"
    assert records[3].detail.model_request is not None
    assert records[3].detail.model_request.surface_seq == 2
    assert records[3].detail.model_request.messages == (
        {"role": "user", "content": "请评价"},
    )
    assert records[4].summary == "correctness=CORRECT · confidence=1 · missingPoints=0 项 · valid"
    assert records[4].status == "complete"
    assert records[4].duration_ms == 3
    assert records[4].detail.model_response is not None
    assert records[4].detail.model_response.input_tokens == 120
    assert records[4].detail.model_response.output_tokens == 30
    assert records[5].kind == "model_error"
    assert records[5].status == "failed"
    assert records[5].duration_ms == 30000
    assert records[5].detail.model_error is not None
    assert records[5].detail.model_error.error_type == "TIMEOUT"
    assert records[6].summary == "AI_EVALUATING → WAIT_STUDENT_ACTION"
    assert records[6].detail.state_change is not None
    assert records[6].detail.state_change.reason == "done"
    assert records[7].status == "pending"


def test_trajectory_record_carries_run_scoped_index_and_parent_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        event(1, "user.message", {"text": "第一轮", "inputType": "text"}, run_id="run_1"),
        event(2, "user.message", {"text": "第二轮", "inputType": "voice"}, run_id="run_2"),
    ]
    trajectory = build_service(monkeypatch, events).build_trajectory(42)

    first_run, second_run = trajectory.runs
    assert [record.index for record in first_run.records] == [1]
    assert [record.index for record in second_run.records] == [1]
    assert first_run.records[0].summary == "第一轮"
    assert second_run.records[0].detail.user is not None
    assert second_run.records[0].detail.user.input_type == "voice"
    assert first_run.records[0].occurred_at == BASE_TIME + timedelta(seconds=1)
    # run.records 与顶层 events 对同一事件给出相同投影。
    assert first_run.records[0].event_id == trajectory.events[0].event_id


def test_trajectory_reads_legacy_model_responded_without_raw_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rawContent 是后加的展示字段，缺失它不得让整个投影抛异常。"""
    events = [
        event(
            1,
            "model.requested",
            {
                "provider": "test-ai",
                "model": "test-model",
                "messages": [{"role": "user", "content": "提问"}],
                "surfaceSeq": 0,
            },
            run_id="run_1",
        ),
        event(
            2,
            "model.responded",
            {"output": {"correctness": "WRONG"}, "validation": "valid", "durationMs": 29946},
            run_id="run_1",
            parent_event_id="evt_1",
        ),
    ]
    trajectory = build_service(monkeypatch, events).build_trajectory(42)

    request_record, response_record = trajectory.events
    assert request_record.status == "complete"
    assert response_record.summary == "correctness=WRONG · valid"
    assert response_record.duration_ms == 29946
    assert response_record.detail.model_response is not None
    assert response_record.detail.model_response.raw_content is None
    assert trajectory.runs[0].steps[0].duration_ms == 29946


def test_trajectory_detail_only_carries_the_used_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """detail 里未使用的键必须是缺省而不是 null，否则前端会多出空页签。"""
    events = [
        event(0, "session.started", {}, run_id=None),
        event(1, "user.message", {"text": "内容", "inputType": "text"}, run_id="run_1"),
        event(
            2,
            "state.changed",
            {"from": "A", "to": "B", "reason": "r"},
            run_id="run_1",
            parent_event_id="evt_1",
        ),
    ]
    trajectory = build_service(monkeypatch, events).build_trajectory(42)

    assert [
        sorted(record.detail.model_dump(exclude_none=True).keys())
        for record in trajectory.events
    ] == [["session"], ["user"], ["state_change"]]
    # 未使用的键在投影模型里就是 None，序列化时被 exclude_none 剔除。
    assert trajectory.events[0].detail.user is None
    assert trajectory.events[1].detail.state_change is None
