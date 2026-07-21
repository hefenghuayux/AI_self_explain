import logging
import sys
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from pythonjsonlogger.json import JsonFormatter

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    return request_id_context.get()


def new_request_id() -> str:
    return uuid4().hex


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "requestId"):
            record.requestId = current_request_id()
        return True


def configure_logging(
    log_dir: Path | None = None, max_size_mib: int = 10, backup_count: int = 5
) -> None:
    formatter = JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(requestId)s",
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
