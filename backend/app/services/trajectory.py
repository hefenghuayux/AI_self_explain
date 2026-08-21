from collections import defaultdict

from sqlalchemy.orm import Session as DatabaseSession

from app.models.session_event import SessionEvent
from app.schemas.session_event import ModelFailedData, ModelRespondedData, StateChangedData
from app.schemas.session_projection import (
    ModelCallStep,
    StateChangeStep,
    Trajectory,
    TrajectoryRun,
    TrajectoryStep,
    UserInputStep,
)
from app.services.event_store import EventStore


class TrajectoryService:
    def __init__(self, database_session: DatabaseSession) -> None:
        self.event_store = EventStore(database_session)

    def build_trajectory(self, session_id: int) -> Trajectory:
        events_by_run: dict[str, list[SessionEvent]] = defaultdict(list)
        for event in self.event_store.list_events(session_id):
            if event.run_id is not None:
                events_by_run[event.run_id].append(event)

        runs = [
            self._build_run(run_id, events)
            for run_id, events in sorted(events_by_run.items(), key=lambda item: item[1][0].seq)
        ]
        return Trajectory(session_id=session_id, runs=tuple(runs))

    def _build_run(self, run_id: str, events: list[SessionEvent]) -> TrajectoryRun:
        results_by_request: dict[str, list[SessionEvent]] = defaultdict(list)
        for event in events:
            if event.event_type in {"model.responded", "model.failed"}:
                if event.parent_event_id is not None:
                    results_by_request[event.parent_event_id].append(event)

        steps: list[tuple[int, TrajectoryStep]] = []
        for event in events:
            if event.event_type == "user.message":
                steps.append(
                    (
                        event.seq,
                        UserInputStep(event_seq=event.seq, summary="学生提交自讲"),
                    )
                )
            elif event.event_type == "model.requested":
                steps.append((event.seq, self._model_call_step(event, results_by_request)))
            elif event.event_type == "state.changed":
                data = StateChangedData.model_validate(event.data)
                steps.append(
                    (
                        event.seq,
                        StateChangeStep(event_seq=event.seq, from_=data.from_, to=data.to),
                    )
                )

        steps.sort(key=lambda item: item[0])
        return TrajectoryRun(
            run_id=run_id,
            started_at=events[0].occurred_at,
            steps=tuple(step for _, step in steps),
        )

    def _model_call_step(
        self,
        request: SessionEvent,
        results_by_request: dict[str, list[SessionEvent]],
    ) -> ModelCallStep:
        results = results_by_request.get(request.event_id, [])
        if len(results) > 1:
            raise ValueError(f"模型请求存在多个直接结果事件：{request.event_id}")
        if not results:
            return ModelCallStep(request_seq=request.seq, status="pending")

        result = results[0]
        if result.event_type == "model.failed":
            data = ModelFailedData.model_validate(result.data)
            status = "failed"
        else:
            data = ModelRespondedData.model_validate(result.data)
            status = "success"
        return ModelCallStep(
            request_seq=request.seq,
            result_seq=result.seq,
            status=status,
            duration_ms=data.durationMs,
        )
