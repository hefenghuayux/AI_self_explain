import logging
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

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


class CompactTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        event_name = getattr(record, "eventName", "runtime.log")
        fields = [timestamp, f"{record.levelname:<5}", str(event_name)]
        for field_name in (
            "method",
            "path",
            "statusCode",
            "purpose",
            "model",
            "durationMs",
            "errorType",
            "legacyFields",
        ):
            value = getattr(record, field_name, None)
            if value is not None:
                suffix = "ms" if field_name == "durationMs" else ""
                fields.append(f"{value}{suffix}")
        session_id = getattr(record, "sessionId", None)
        request_id = getattr(record, "requestId", None)
        if session_id is not None:
            fields.append(f"sid={session_id}")
        if request_id:
            fields.append(f"rid={str(request_id)[:12]}")
        if record.levelno >= logging.ERROR:
            fields.append(f"msg={record.getMessage()}")
        line = " ".join(fields)
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def _archive_json_application_log(log_path: Path) -> None:
    if not log_path.exists() or log_path.stat().st_size == 0:
        return
    with log_path.open("r", encoding="utf-8") as log_file:
        first_character = log_file.read(1)
    if first_character != "{":
        return
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    log_path.replace(log_path.with_name(f"application-{timestamp}.json.log"))


def configure_logging(
    log_dir: Path | None = None, max_size_mib: int = 10, backup_count: int = 5
) -> None:
    formatter = CompactTextFormatter()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(formatter)
    handlers: list[logging.Handler] = [handler]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "application.log"
        _archive_json_application_log(log_path)
        file_handler = RotatingFileHandler(
            log_path,
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
    logging.getLogger("httpx").setLevel(logging.DEBUG)
