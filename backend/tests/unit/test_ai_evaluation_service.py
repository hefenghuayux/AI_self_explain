import json

from app.services.ai_evaluation import AIModelClient


def test_ai_model_client_uses_configured_chat_completions_protocol(settings, monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        is_error = False
        text = '{"choices":[{"message":{"content":"{\\\"ok\\\":true}"}}]}'

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": '{"ok":true}'}}]}

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

        def post(
            self, url: str, *, headers: dict[str, str], json: dict[str, object]
        ) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("app.services.ai_evaluation.httpx.Client", FakeClient)
    schema = {"type": "object", "additionalProperties": False}

    response = AIModelClient(settings).evaluate("评价提示词", schema)

    assert response.content == '{"ok":true}'
    assert captured["url"] == "https://ai.test/v1/chat/completions"
    assert captured["timeout"] == settings.ai_request_timeout_seconds
    request_json = captured["json"]
    assert request_json["model"] == settings.ai_model
    assert request_json["response_format"] == {"type": "json_object"}
    assert json.loads(response.raw_response)["choices"]
