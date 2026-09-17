import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.explanation_attempt import ExplanationAttempt
from app.models.question import Question
from app.models.session import Session
from app.schemas.model_request_snapshot import (
    ModelRequestBlocks,
    ModelRequestMessage,
    ModelRequestPrivacy,
    ModelRequestSnapshot,
    ModelTransportSnapshot,
)
from app.services.ai_evaluation import AIModelClient, _render_prompt


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
        session=Session(round=1, support_count_round=0),
        attempt=ExplanationAttempt(confirmed_text="两个一相加等于二。"),
        schema={"type": "object", "additionalProperties": False},
        validation_errors=[],
        model=settings.ai_model,
        prompt_version=settings.prompt_version,
    )

    response = AIModelClient(settings, FakeClient()).evaluate(request)

    assert response.content == '{"ok":true}'
    assert captured["url"] == "https://ai.test/v1/chat/completions"
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
    assert request.blocks.session_context == {
        "taskType": "EXPLANATION",
        "progressContext": {
            "previousExplanations": [],
            "previousTeaching": [],
        },
        "round": 2,
        "supportCountRound": 3,
    }
    assert request.blocks.user_input == {"confirmedText": "两个一相加等于二。"}
    assert request.blocks.memory_context is None


def test_app_reuses_and_closes_ai_http_client(settings) -> None:
    application = create_app(settings)

    with TestClient(application):
        http_client = application.state.ai_http_client
        assert not http_client.is_closed
        assert http_client.timeout.connect == settings.ai_request_timeout_seconds

    assert http_client.is_closed


def test_snapshot_schema_v1_0_backward_compatible() -> None:
    """schemaVersion="1.0" 的旧快照仍能被当前模型读取。"""
    snapshot = ModelRequestSnapshot(
        schema_version="1.0",
        purpose="AI_EVALUATION",
        prompt_version="v1",
        blocks=ModelRequestBlocks(
            system_instructions="旧模板",
            question_context={"q": "1+1="},
            session_context={"round": 1},
            user_input={"confirmedText": "2"},
            retry_context={"validationErrors": []},
        ),
        transport=ModelTransportSnapshot(
            model="test-model",
            messages=[ModelRequestMessage(role="user", content="旧请求")],
            response_format={"type": "json_object"},
        ),
        privacy=ModelRequestPrivacy(
            contains_student_content=True,
            contains_answer_material=True,
            contains_memory=False,
        ),
    )
    db_value = snapshot.database_value()
    assert db_value["schemaVersion"] == "1.0"
    assert db_value["transport"]["messages"] == [{"role": "user", "content": "旧请求"}]
    payload = snapshot.transport_payload()
    assert payload["messages"] == [{"role": "user", "content": "旧请求"}]
    # 1.0 快照不包含 taskInstructions
    assert "taskInstructions" not in db_value["blocks"]
    assert "taskInstructions" not in snapshot.blocks.model_dump(by_alias=True, exclude_none=True)


def test_snapshot_schema_v1_1_multi_message_serialization() -> None:
    """schemaVersion="1.1" 支持 system + 多条 user 消息序列化。"""
    snapshot = ModelRequestSnapshot(
        schema_version="1.1",
        purpose="AI_EVALUATION",
        prompt_version="v1",
        blocks=ModelRequestBlocks(
            system_instructions="共享 system 内容",
            question_context={"q": "1+1="},
            session_context={"round": 1},
            task_instructions="评价任务指令",
            user_input={"confirmedText": "2"},
            retry_context={"validationErrors": []},
        ),
        transport=ModelTransportSnapshot(
            model="test-model",
            messages=[
                ModelRequestMessage(role="system", content="共享 system 内容"),
                ModelRequestMessage(role="user", content="会话级上下文"),
                ModelRequestMessage(role="user", content="共享历史"),
                ModelRequestMessage(role="user", content="任务指令"),
                ModelRequestMessage(role="user", content="本轮数据"),
            ],
            response_format={"type": "json_object"},
        ),
        privacy=ModelRequestPrivacy(
            contains_student_content=True,
            contains_answer_material=True,
            contains_memory=False,
        ),
    )
    db_value = snapshot.database_value()
    assert db_value["schemaVersion"] == "1.1"
    assert db_value["blocks"]["taskInstructions"] == "评价任务指令"
    messages = db_value["transport"]["messages"]
    assert len(messages) == 5
    assert messages[0] == {"role": "system", "content": "共享 system 内容"}
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "user"
    assert messages[3]["role"] == "user"
    assert messages[4]["role"] == "user"
    payload = snapshot.transport_payload()
    assert len(payload["messages"]) == 5
    assert payload["messages"][0]["role"] == "system"
