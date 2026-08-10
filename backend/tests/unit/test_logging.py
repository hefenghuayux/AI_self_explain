import json
import logging

import pytest

from app.core.config import Settings
from app.core.logging import bind_trace_context, configure_logging, reset_trace_context


def test_logging_outputs_json_without_api_keys(
    capsys: pytest.CaptureFixture[str], settings: Settings
) -> None:
    configure_logging()
    logging.getLogger("test").info(
        "配置校验完成：%s", settings, extra={"operation": "config_validation"}
    )

    output = capsys.readouterr().out
    record = json.loads(output)
    assert record["level"] == "INFO"
    assert record["operation"] == "config_validation"
    assert "test-ai-secret" not in output
    assert "test-asr-secret" not in output


def test_logging_writes_rotating_file(tmp_path) -> None:
    configure_logging(tmp_path, max_size_mib=1, backup_count=2)
    logging.getLogger("test").info("轮转文件测试")

    log_file = tmp_path / "application.log"
    assert log_file.exists()
    record = json.loads(log_file.read_text(encoding="utf-8").splitlines()[-1])
    assert record["message"] == "轮转文件测试"


def test_logging_includes_trace_context(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    tokens = bind_trace_context(
        request_id="request-1",
        trace_id="trace-1",
        span_id="span-1",
        parent_span_id="span-parent",
        session_id=42,
    )
    try:
        logging.getLogger("test").info("链路上下文测试")
    finally:
        reset_trace_context(tokens)

    record = json.loads(capsys.readouterr().out)
    assert record["requestId"] == "request-1"
    assert record["traceId"] == "trace-1"
    assert record["spanId"] == "span-1"
    assert record["parentSpanId"] == "span-parent"
    assert record["sessionId"] == 42
