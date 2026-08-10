import logging
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from pythonjsonlogger.json import JsonFormatter

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
trace_id_context: ContextVar[str | None] = ContextVar("trace_id", default=None)
span_id_context: ContextVar[str | None] = ContextVar("span_id", default=None)
parent_span_id_context: ContextVar[str | None] = ContextVar("parent_span_id", default=None)
session_id_context: ContextVar[int | None] = ContextVar("session_id", default=None)


@dataclass(frozen=True)
class TraceContextTokens:
    request_id: object
    trace_id: object
    span_id: object
    parent_span_id: object
    session_id: object


def current_request_id() -> str | None:
    return request_id_context.get()


def new_correlation_id() -> str:
    return uuid4().hex


def bind_trace_context(
    *,
    request_id: str,
    trace_id: str,
    span_id: str,
    parent_span_id: str | None = None,
    session_id: int | None = None,
) -> TraceContextTokens:
    return TraceContextTokens(
        request_id=request_id_context.set(request_id),
        trace_id=trace_id_context.set(trace_id),
        span_id=span_id_context.set(span_id),
        parent_span_id=parent_span_id_context.set(parent_span_id),
        session_id=session_id_context.set(session_id),
    )


def reset_trace_context(tokens: TraceContextTokens) -> None:
    session_id_context.reset(tokens.session_id)
    parent_span_id_context.reset(tokens.parent_span_id)
    span_id_context.reset(tokens.span_id)
    trace_id_context.reset(tokens.trace_id)
    request_id_context.reset(tokens.request_id)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context_fields = {
            "requestId": request_id_context.get(),
            "traceId": trace_id_context.get(),
            "spanId": span_id_context.get(),
            "parentSpanId": parent_span_id_context.get(),
            "sessionId": session_id_context.get(),
        }
        for field_name, value in context_fields.items():
            if not hasattr(record, field_name):
                setattr(record, field_name, value)
        return True


def configure_logging(
    log_dir: Path | None = None, max_size_mib: int = 10, backup_count: int = 5
) -> None:
    formatter = JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s "
        "%(requestId)s %(traceId)s %(spanId)s %(parentSpanId)s %(sessionId)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(formatter)
    handlers: list[logging.Handler] = [handler]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "application.log",
            maxBytes=max_size_mib * 1024 * 1024,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.addFilter(RequestContextFilter())
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    for configured_handler in handlers:
        root_logger.addHandler(configured_handler)
    root_logger.setLevel(logging.INFO)
