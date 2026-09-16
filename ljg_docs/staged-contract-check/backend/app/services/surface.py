from sqlalchemy.orm import Session as DatabaseSession

from app.schemas.session_event import ContextAddedData, UserMessageData
from app.schemas.session_projection import Surface, SurfaceContext, SurfaceMessage
from app.services.event_store import EventStore


class SurfaceService:
    def __init__(self, database_session: DatabaseSession) -> None:
        self.event_store = EventStore(database_session)

    def build_surface(self, session_id: int, as_of_seq: int | None = None) -> Surface:
        if as_of_seq is not None and as_of_seq < 0:
            raise ValueError("as_of_seq 不能小于 0")

        events = self.event_store.list_events(session_id)
        if as_of_seq is not None:
            events = [event for event in events if event.seq <= as_of_seq]

        messages: list[SurfaceMessage] = []
        contexts: list[SurfaceContext] = []
        for event in events:
            if event.event_type == "user.message":
                data = UserMessageData.model_validate(event.data)
                messages.append(SurfaceMessage(seq=event.seq, role="user", content=data.text))
            elif event.event_type == "context.added":
                data = ContextAddedData.model_validate(event.data)
                contexts.append(
                    SurfaceContext(
                        seq=event.seq,
                        kind=data.kind,
                        source=data.source,
                        content=data.content,
                    )
                )

        return Surface(
            session_id=session_id,
            as_of_seq=events[-1].seq if events else -1,
            messages=tuple(messages),
            contexts=tuple(contexts),
        )
