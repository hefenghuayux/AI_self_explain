import json
from types import SimpleNamespace

import httpx
import pytest
from app.services.context_compaction import CompactionError, ContextCompactor
from pydantic import SecretStr


class FakeTokenizer:
    def count_text(self, value: str) -> int:
        return len(value)


class FakeClient:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.content = content
        self.finish_reason = finish_reason
        self.request = None

    def post(self, endpoint, *, headers, json, timeout):
        self.request = {"endpoint": endpoint, "headers": headers, "json": json, "timeout": timeout}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": self.content},
                        "finish_reason": self.finish_reason,
                    }
                ]
            },
            request=httpx.Request("POST", endpoint),
        )


def make_compactor(client: FakeClient) -> ContextCompactor:
    settings = SimpleNamespace(
        ai_base_url="https://example.test/v1",
        ai_api_key=SecretStr("test-key"),
        ai_model="deepseek-flash",
        ai_request_timeout_seconds=30,
        context_compaction_wait_timeout_seconds=30,
        context_compaction_summary_max_tokens=1024,
    )
    return ContextCompactor(settings, client, FakeTokenizer())


def test_summary_request_uses_json_wrapper_and_returns_markdown_body():
    client = FakeClient('{"summary":"## 学生已表达的理解\\n- 1+1=2"}')
    compactor = make_compactor(client)

    result = compactor._summarize([{"role": "user", "content": "json"}], 100)

    assert result == "## 学生已表达的理解\n- 1+1=2"
    assert client.request["json"]["response_format"] == {"type": "json_object"}
    assert client.request["json"]["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize(
    ("content", "finish_reason", "code"),
    [
        ("## 学生已表达的理解\n- 纯 Markdown", "stop", "CONTEXT_COMPACTION_INVALID_RESPONSE"),
        ('{"summary":"正文","extra":"忽略"}', "stop", "CONTEXT_COMPACTION_INVALID_RESPONSE"),
        (json.dumps({"summary": ""}), "stop", "CONTEXT_COMPACTION_EMPTY_SUMMARY"),
        ('{"summary":"不完整"', "stop", "CONTEXT_COMPACTION_INVALID_RESPONSE"),
        ('{"summary":"截断"}', "length", "CONTEXT_COMPACTION_INCOMPLETE_SUMMARY"),
    ],
)
def test_summary_response_contract_is_validated(content, finish_reason, code):
    compactor = make_compactor(FakeClient(content, finish_reason))

    with pytest.raises(CompactionError) as error:
        compactor._summarize([{"role": "user", "content": "json"}], 100)

    assert error.value.code == code
