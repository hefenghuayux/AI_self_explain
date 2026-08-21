from collections import defaultdict

from sqlalchemy.orm import Session as DatabaseSession

from app.models.session_event import SessionEvent
from app.schemas.session_projection import Trace, TraceNode
from app.services.event_store import EventStore


class TraceService:
    def __init__(self, database_session: DatabaseSession) -> None:
        self.event_store = EventStore(database_session)

    def build_trace(self, session_id: int, run_id: str) -> Trace:
        if not run_id:
            raise ValueError("run_id 不能为空")

        events = [
            event for event in self.event_store.list_events(session_id) if event.run_id == run_id
        ]
        events_by_id = {event.event_id: event for event in events}
        children_by_parent: dict[str, list[SessionEvent]] = defaultdict(list)
        roots: list[SessionEvent] = []
        for event in events:
            if event.parent_event_id is None or event.parent_event_id not in events_by_id:
                roots.append(event)
            else:
                children_by_parent[event.parent_event_id].append(event)

        return Trace(
            session_id=session_id,
            run_id=run_id,
            roots=tuple(self._node(event, children_by_parent) for event in roots),
        )

    def _node(
        self,
        event: SessionEvent,
        children_by_parent: dict[str, list[SessionEvent]],
    ) -> TraceNode:
        children = sorted(children_by_parent.get(event.event_id, []), key=lambda item: item.seq)
        return TraceNode(
            seq=event.seq,
            event_type=event.event_type,
            children=tuple(self._node(child, children_by_parent) for child in children),
        )
