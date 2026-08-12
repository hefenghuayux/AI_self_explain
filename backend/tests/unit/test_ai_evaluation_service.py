import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.ai_evaluation import AIModelClient


def test_ai_model_client_uses_configured_chat_completions_protocol(settings) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        is_error = False
        text = '{"choices":[{"message":{"content":"{\\\"ok\\\":true}"}}]}'

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": '{"ok":true}'}}]}

    class FakeClient:
        def post(
            self, url: str, *, headers: dict[str, str], json: dict[str, object]
        ) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    schema = {"type": "object", "additionalProperties": False}

    http_client = FakeClient()
    response = AIModelClient(settings, http_client).evaluate("评价提示词", schema)

    assert response.content == '{"ok":true}'
    assert captured["url"] == "https://ai.test/v1/chat/completions"
    request_json = captured["json"]
    assert request_json["model"] == settings.ai_model
    assert request_json["response_format"] == {"type": "json_object"}
    assert json.loads(response.raw_response)["choices"]


def test_app_reuses_and_closes_ai_http_client(settings) -> None:
    application = create_app(settings)

    with TestClient(application):
        http_client = application.state.ai_http_client
        assert not http_client.is_closed
        assert http_client.timeout.connect == settings.ai_request_timeout_seconds

    assert http_client.is_closed
