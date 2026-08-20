from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DatabaseSession

from app.models.session import Session
from app.models.session_event import SessionEvent
from app.schemas.session_event import EVENT_DATA_SCHEMAS, EventType


class SessionEventError(RuntimeError):
    pass


class SessionNotFoundError(SessionEventError):
    pass


class EventNotFoundError(SessionEventError):
    pass


class InvalidEventDataError(SessionEventError):
    pass


class EventStore:
    def __init__(self, database_session: DatabaseSession) -> None:
        self.database_session = database_session

    def create_session(self, session: Session) -> Session:
        if session.id is None:
            raise ValueError("Session 必须先写入数据库再创建启动事件")
        self.append(session.id, "session.started", {})
        return session

    def append(
        self,
        session_id: int,
        event_type: EventType | str,
        data: dict[str, object],
        run_id: str | None = None,
        parent_event_id: str | None = None,
    ) -> SessionEvent:
        self._acquire_sqlite_write_lock()
        if self.database_session.get(Session, session_id) is None:
            raise SessionNotFoundError(f"会话不存在：{session_id}")

        validated_data = self._validate_data(event_type, data)
        last_seq = self.database_session.scalar(
            select(func.max(SessionEvent.seq)).where(SessionEvent.session_id == session_id)
        )
        next_seq = 0 if last_seq is None else last_seq + 1

        if parent_event_id is not None:
            parent = self.database_session.scalar(
                select(SessionEvent).where(
                    SessionEvent.session_id == session_id,
                    SessionEvent.event_id == parent_event_id,
                )
            )
            if parent is None:
                raise InvalidEventDataError(f"父事件不属于当前会话或不存在：{parent_event_id}")

        if event_type == "session.started":
            if next_seq != 0 or run_id is not None or parent_event_id is not None:
                raise InvalidEventDataError("session.started 必须是无 runId、无父事件的 seq=0 事件")

        event = SessionEvent(
            session_id=session_id,
            seq=next_seq,
            event_id=f"evt_{uuid4().hex}",
            run_id=run_id,
            parent_event_id=parent_event_id,
            event_type=event_type,
            occurred_at=datetime.now(UTC),
            data=validated_data,
        )
        self.database_session.add(event)
        self.database_session.flush()
        return event

    def list_events(
        self, session_id: int, after_seq: int | None = None, limit: int | None = None
    ) -> list[SessionEvent]:
        self._require_session(session_id)
        statement = select(SessionEvent).where(SessionEvent.session_id == session_id)
        if after_seq is not None:
            statement = statement.where(SessionEvent.seq > after_seq)
        statement = statement.order_by(SessionEvent.seq)
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit 必须大于 0")
            statement = statement.limit(limit)
        return list(self.database_session.scalars(statement))

    def get_event(self, session_id: int, seq: int) -> SessionEvent:
        self._require_session(session_id)
        event = self.database_session.scalar(
            select(SessionEvent).where(
                SessionEvent.session_id == session_id,
                SessionEvent.seq == seq,
            )
        )
        if event is None:
            raise EventNotFoundError(f"事件不存在：session={session_id}, seq={seq}")
        return event

    def _require_session(self, session_id: int) -> None:
        if self.database_session.get(Session, session_id) is None:
            raise SessionNotFoundError(f"会话不存在：{session_id}")

    def _validate_data(self, event_type: str, data: object) -> dict[str, object]:
        schema = EVENT_DATA_SCHEMAS.get(event_type)
        if schema is None:
            raise InvalidEventDataError(f"不支持的事件类型：{event_type}")
        if not isinstance(data, dict):
            raise InvalidEventDataError("事件 data 必须是 JSON object")
        try:
            validated = schema.model_validate(data)
        except ValidationError as error:
            raise InvalidEventDataError(f"事件 data 校验失败：{error}") from error
        return validated.model_dump(by_alias=True, exclude_none=True)

    def _acquire_sqlite_write_lock(self) -> None:
        connection = self.database_session.connection()
        if connection.dialect.name != "sqlite":
            return
        driver_connection = connection.connection.driver_connection
        if not driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
