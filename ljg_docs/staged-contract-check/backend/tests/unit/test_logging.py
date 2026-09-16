import logging
import re

import pytest

from app.core.config import Settings
from app.core.logging import bind_trace_context, configure_logging, reset_trace_context


def test_logging_outputs_compact_text_without_api_keys(
    capsys: pytest.CaptureFixture[str], settings: Settings
) -> None:
    configure_logging()
    logging.getLogger("test").info(
        "配置校验完成：%s",
        settings,
        extra={"eventName": "config.validated", "operation": "config_validation"},
    )

    output = capsys.readouterr().out
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} INFO\s+config\.validated", output)
    assert output.count("\n") == 1
    assert "test-ai-secret" not in output
    assert "test-asr-secret" not in output


def test_logging_writes_rotating_file(tmp_path) -> None:
    configure_logging(tmp_path, max_size_mib=1, backup_count=2)
    logging.getLogger("test").info("轮转文件测试", extra={"eventName": "log.rotation_test"})

    log_file = tmp_path / "application.log"
    assert log_file.exists()
    assert "INFO  log.rotation_test" in log_file.read_text(encoding="utf-8")


def test_logging_archives_existing_json_application_log(tmp_path) -> None:
    log_file = tmp_path / "application.log"
    log_file.write_text('{"level":"INFO"}\n', encoding="utf-8")

    configure_logging(tmp_path, max_size_mib=1, backup_count=2)
    logging.getLogger("test").info("新格式", extra={"eventName": "log.compact"})

    archived = list(tmp_path.glob("application-*.json.log"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == '{"level":"INFO"}\n'
    assert "log.compact" in log_file.read_text(encoding="utf-8")


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
        logging.getLogger("test").info(
            "链路上下文测试", extra={"eventName": "trace.context_test", "durationMs": 12}
        )
    finally:
        reset_trace_context(tokens)

    output = capsys.readouterr().out
    assert "trace.context_test 12ms sid=42 rid=request-1" in output
