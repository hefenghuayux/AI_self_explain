import json

from sqlalchemy.orm import Session as DatabaseSession

from app.models.session_event import SessionEvent
from app.schemas.model_request_snapshot import ModelRequestSnapshot
from app.services.event_store import EventStore


class SessionEventLog:
    def __init__(self, database_session: DatabaseSession) -> None:
        self.database_session = database_session
        self.event_store = EventStore(database_session)

    def latest_event_id(self, session_id: int, run_id: str) -> str | None:
        events = self.event_store.list_events(session_id)
        for event in reversed(events):
            if event.run_id == run_id:
                return event.event_id
        return None

    def append_contexts(
        self,
        *,
        session_id: int,
        run_id: str,
        request: ModelRequestSnapshot,
        question_source: str,
        parent_event_id: str | None,
    ) -> None:
        self.event_store.append(
            session_id=session_id,
            event_type="context.added",
            run_id=run_id,
            parent_event_id=parent_event_id,
            data={
                "kind": "question",
                "source": question_source,
                "content": request.blocks.question_context,
            },
        )
        rubric_points = request.blocks.question_context.get("rubricPoints")
        if isinstance(rubric_points, list):
            self.event_store.append(
                session_id=session_id,
                event_type="context.added",
                run_id=run_id,
                parent_event_id=parent_event_id,
                data={
                    "kind": "rubric",
                    "source": f"{question_source}:rubric",
                    "content": {"rubricPoints": rubric_points},
                },
            )
        self.event_store.append(
            session_id=session_id,
            event_type="context.added",
            run_id=run_id,
            parent_event_id=parent_event_id,
            data={
                "kind": "session_state",
                "source": "session.state",
                "content": request.blocks.session_context,
            },
        )
        self.database_session.commit()

    def append_model_requested(
        self,
        *,
        session_id: int,
        run_id: str,
        request: ModelRequestSnapshot,
        provider: str,
        parent_event_id: str | None,
    ) -> SessionEvent:
        event = self.event_store.append(
            session_id=session_id,
            event_type="model.requested",
            run_id=run_id,
            parent_event_id=parent_event_id,
            data={
                "provider": provider,
                "model": request.transport.model,
                "messages": request.transport.model_dump(mode="json")["messages"],
                "surfaceSeq": self._surface_seq(session_id),
            },
        )
        self.database_session.commit()
        self.database_session.refresh(event)
        return event

    def append_model_responded(
        self,
        *,
        session_id: int,
        run_id: str,
        response_content: str,
        validation: str,
        duration_ms: int,
        parent_event_id: str,
    ) -> SessionEvent:
        try:
            output = json.loads(response_content)
        except json.JSONDecodeError:
            output = {}
        if not isinstance(output, dict):
            output = {}
        event = self.event_store.append(
            session_id=session_id,
            event_type="model.responded",
            run_id=run_id,
            parent_event_id=parent_event_id,
            data={
                "output": output,
                "rawContent": response_content,
                "durationMs": duration_ms,
                "validation": validation,
            },
        )
        self.database_session.commit()
        self.database_session.refresh(event)
        return event

    def append_model_failed(
        self,
        *,
        session_id: int,
        run_id: str,
        error_type: str,
        message: str,
        duration_ms: int,
        parent_event_id: str,
    ) -> SessionEvent:
        if error_type == "AI_TIMEOUT":
            mapped_error_type = "TIMEOUT"
        elif error_type == "AI_SERVICE_ERROR" and "HTTP " in message:
            mapped_error_type = "HTTP_ERROR"
        elif error_type == "AI_SERVICE_ERROR" and "响应不包含" in message:
            mapped_error_type = "INVALID_RESPONSE"
        elif error_type == "AI_SERVICE_ERROR":
            mapped_error_type = "CONNECTION_ERROR"
        else:
            mapped_error_type = "UNKNOWN"
        event = self.event_store.append(
            session_id=session_id,
            event_type="model.failed",
            run_id=run_id,
            parent_event_id=parent_event_id,
            data={
                "errorType": mapped_error_type,
                "message": message,
                "durationMs": duration_ms,
            },
        )
        self.database_session.commit()
        self.database_session.refresh(event)
        return event

    def _surface_seq(self, session_id: int) -> int:
        events = self.event_store.list_events(session_id)
        return events[-1].seq if events else 0
