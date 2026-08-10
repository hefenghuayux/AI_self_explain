import json

from app.models.explanation_attempt import ExplanationAttempt
from app.models.question import Question
from app.models.session import Session
from app.services.ai_evaluation import AIModelClient, _render_prompt


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
    request = _render_prompt(
        question=Question(
            question_content="1+1 等于多少？",
            standard_answer="2",
            rubric_points=["正确计算加法"],
            common_errors=[],
            alternative_solutions=[],
            layered_hints=[],
            guided_questions=[],
            full_solution="1+1=2",
        ),
        session=Session(round=1, support_count_round=0, covered_points_current_round=[]),
        attempt=ExplanationAttempt(confirmed_text="两个一相加等于二。"),
        schema={"type": "object", "additionalProperties": False},
        validation_errors=[],
        model=settings.ai_model,
        prompt_version=settings.prompt_version,
    )

    response = AIModelClient(settings).evaluate(request)

    assert response.content == '{"ok":true}'
    assert captured["url"] == "https://ai.test/v1/chat/completions"
    assert captured["timeout"] == settings.ai_request_timeout_seconds
    request_json = captured["json"]
    assert request_json == request.transport_payload()
    assert request_json["model"] == settings.ai_model
    assert request_json["response_format"] == {"type": "json_object"}
    assert settings.ai_api_key.get_secret_value() not in json.dumps(
        request.database_value(), ensure_ascii=False
    )
    assert json.loads(response.raw_response)["choices"]


def test_evaluation_snapshot_separates_session_state_from_transport_prompt() -> None:
    question = Question(
        question_content="1+1 等于多少？",
        standard_answer="2",
        rubric_points=["正确计算加法"],
        common_errors=[],
        alternative_solutions=[],
        layered_hints=[],
        guided_questions=[],
        full_solution="1+1=2",
    )
    session = Session(
        round=2,
        support_count_round=3,
        covered_points_current_round=["不应进入评价上下文"],
    )
    attempt = ExplanationAttempt(confirmed_text="两个一相加等于二。")

    request = _render_prompt(
        question=question,
        session=session,
        attempt=attempt,
        schema={"type": "object"},
        validation_errors=[],
        model="test-model",
        prompt_version="evaluation-v1",
    )
    prompt = request.transport.messages[0].content

    assert '"confirmedText": "两个一相加等于二。"' in prompt
    assert '"round"' not in prompt
    assert '"supportCountRound"' not in prompt
    assert '"coveredPointsCurrentRound"' not in prompt
    assert request.blocks.session_context == {
        "round": 2,
        "supportCountRound": 3,
        "coveredPointsCurrentRound": ["不应进入评价上下文"],
    }
    assert request.blocks.user_input == {"confirmedText": "两个一相加等于二。"}
    assert request.blocks.memory_context is None
