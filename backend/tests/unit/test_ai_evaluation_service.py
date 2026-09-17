# -*- coding: utf-8 -*-
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.explanation_attempt import ExplanationAttempt
from app.models.question import Question
from app.models.session import Session
from app.models.support_event import SupportEvent
from app.schemas.model_request_snapshot import (
    ModelRequestBlocks,
    ModelRequestMessage,
    ModelRequestPrivacy,
    ModelRequestSnapshot,
    ModelTransportSnapshot,
)
from app.services.ai_evaluation import (
    AIModelClient,
    _render_prompt,
    build_progress_context,
    _truncate_by_interaction,
)


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

    # messages[0] system: shared_system
    assert request.transport.messages[0].role == "system"
    assert "后端模型组件" in request.transport.messages[0].content

    # messages[4] user: 本轮任务数据包含 confirmedText
    assert '"confirmedText"' in request.transport.messages[4].content
    assert '"两个一相加等于二。"' in request.transport.messages[4].content

    # 会话状态（round, supportCountRound）不出现在 transport 消息中
    for i in range(5):
        assert '"round"' not in request.transport.messages[i].content
        assert '"supportCountRound"' not in request.transport.messages[i].content

    # blocks 保持会话状态分离
    assert request.blocks.session_context == {
        "taskType": "EXPLANATION",
        "progressContext": {
            "events": [],
        },
        "round": 2,
        "supportCountRound": 3,
    }
    assert request.blocks.user_input == {"confirmedText": "两个一相加等于二。"}
    assert request.blocks.memory_context is None


def test_evaluation_v1_1_has_five_layer_structure() -> None:
    """_render_prompt 生成 schemaVersion=1.1 的五层消息结构。"""
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
    session = Session(round=1, support_count_round=0)
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

    assert request.schema_version == "1.1"

    messages = request.transport.messages
    assert len(messages) == 5

    # messages[0] system：全局共享前缀
    assert messages[0].role == "system"
    assert "后端模型组件" in messages[0].content
    assert "原因定义" in messages[0].content

    # messages[1] user：会话级稳定上下文（题目数据，不含 outputSchema）
    assert messages[1].role == "user"
    msg1 = json.loads(messages[1].content)
    assert msg1["questionContent"] == "1+1 等于多少？"
    assert "outputSchema" not in msg1

    # messages[2] user：共享历史
    assert messages[2].role == "user"
    msg2 = json.loads(messages[2].content)
    assert "events" in msg2

    # messages[3] user：taskType 固定指令 + JSON Schema
    assert messages[3].role == "user"
    assert "评价器" in messages[3].content
    assert '"type": "object"' in messages[3].content

    # messages[4] user：本轮任务数据
    assert messages[4].role == "user"
    msg4 = json.loads(messages[4].content)
    assert msg4["confirmedText"] == "两个一相加等于二。"
    # 首次请求无重试信息
    assert "previousOutput" not in msg4
    assert "validationErrors" not in msg4

    # blocks
    assert "后端模型组件" in request.blocks.system_instructions
    assert request.blocks.task_instructions is not None
    assert "JSON Schema" in request.blocks.task_instructions


def test_evaluation_v1_1_retry_only_changes_fifth_layer() -> None:
    """重试时只改变 transport.messages[4]（本轮任务数据），前四层不变。"""
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
    session = Session(round=1, support_count_round=0)
    attempt = ExplanationAttempt(confirmed_text="两个一相加等于二。")

    request_original = _render_prompt(
        question=question,
        session=session,
        attempt=attempt,
        schema={"type": "object"},
        validation_errors=[],
        model="test-model",
        prompt_version="evaluation-v1",
    )
    request_retry = _render_prompt(
        question=question,
        session=session,
        attempt=attempt,
        schema={"type": "object"},
        validation_errors=["字段缺失"],
        model="test-model",
        prompt_version="evaluation-v1",
        previous_output='{"wrong": true}',
    )

    orig = request_original.transport.messages
    retry = request_retry.transport.messages

    # 前四层完全一致
    for i in range(4):
        assert orig[i].content == retry[i].content, f"messages[{i}] 应不变"

    # 第五层不同（包含重试信息）
    assert orig[4].content != retry[4].content
    retry_data = json.loads(retry[4].content)
    assert retry_data["validationErrors"] == ["字段缺失"]
    assert retry_data["previousOutput"] == '{"wrong": true}'


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


def _attempt(event_id: int, text: str, created_at: datetime) -> ExplanationAttempt:
    return ExplanationAttempt(
        id=event_id, confirmed_text=text, created_at=created_at, round=1, input_mode="text"
    )


def _support(
    event_id: int,
    created_at: datetime,
    *,
    guided_questions: list[dict[str, str]] | None = None,
    guided_answers: list[dict[str, str]] | None = None,
    follow_up_content: str | None = None,
) -> SupportEvent:
    return SupportEvent(
        id=event_id,
        session_id=1,
        support_type="GIVE_HINT",
        round=1,
        status="SUCCEEDED",
        content="先判断开口方向。",
        support_kind="EVALUATION",
        guided_questions=guided_questions,
        guided_answers=guided_answers,
        follow_up_content=follow_up_content,
        created_at=created_at,
    )


def test_build_progress_context_empty_input() -> None:
    assert build_progress_context(
        previous_attempts=[], previous_support=[], max_interactions=12
    ) == {"events": []}


def test_build_progress_context_orders_by_created_at_not_id() -> None:
    """不比较跨表 ID：即使 attempt id 小于 support id，也按 created_at 排序。"""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    attempt = _attempt(50, "学生第一轮自讲", base)          # id=50
    support = _support(
        10,
        base + timedelta(seconds=1),                       # id=10 但时间更晚
        guided_questions=[{"id": "q1", "question": "最大值在哪取得？"}],
        guided_answers=[{"question_id": "q1", "answer": "看端点"}],
        follow_up_content="对，继续。",
    )
    result = build_progress_context(
        previous_attempts=[attempt], previous_support=[support], max_interactions=12
    )
    events = result["events"]
    assert [event["actor"] for event in events] == ["student", "teacher", "student", "teacher"]
    assert [event["kind"] for event in events] == [
        "explanation",
        "teaching",
        "guided_answer",
        "follow_up",
    ]
    assert [event["seq"] for event in events] == [0, 1, 2, 3]
    assert events[2]["replyTo"] == "support:10"
    assert events[2]["content"][0]["questionId"] == "q1"
    assert events[2]["content"][0]["answer"] == "看端点"


def test_build_progress_context_teaching_event_embeds_questions_text() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    support = _support(
        3,
        base,
        guided_questions=[
            {"id": "q1", "question": "最大值在哪取得？"},
        ],
    )
    events = build_progress_context(
        previous_attempts=[], previous_support=[support], max_interactions=12
    )["events"]
    assert len(events) == 1
    assert events[0]["content"] == "先判断开口方向。\n\n问：最大值在哪取得？"


def test_build_progress_context_default_when_empty() -> None:
    assert build_progress_context(
        previous_attempts=[], previous_support=[], max_interactions=5
    ) == {"events": []}


def test_truncate_keeps_complete_interaction_groups() -> None:
    """一组 teaching + guided_answer 是完整交互，max_interactions=1 时整组保留。"""
    events = [
        {
            "seq": 0,
            "actor": "student",
            "kind": "explanation",
            "content": "旧自讲",
            "interactionId": "attempt:1",
        },
        {
            "seq": 1,
            "actor": "teacher",
            "kind": "teaching",
            "content": "提示 A",
            "interactionId": "support:1",
        },
        {
            "seq": 2,
            "actor": "student",
            "kind": "guided_answer",
            "content": [{"questionId": "q1", "question": "Q", "answer": "A"}],
            "interactionId": "support:1",
            "replyTo": "support:1",
        },
        {
            "seq": 3,
            "actor": "teacher",
            "kind": "teaching",
            "content": "提示 B",
            "interactionId": "support:2",
        },
        {
            "seq": 4,
            "actor": "teacher",
            "kind": "follow_up",
            "content": "跟进 B",
            "interactionId": "support:2:followup",
        },
    ]
    result = _truncate_by_interaction(events, max_interactions=1)
    assert [event["interactionId"] for event in result] == [
        "support:2",
        "support:2:followup",
    ]


def test_truncate_keeps_two_interactions() -> None:
    events = [
        {
            "seq": 0,
            "actor": "student",
            "kind": "explanation",
            "content": "旧自讲",
            "interactionId": "attempt:1",
        },
        {
            "seq": 1,
            "actor": "teacher",
            "kind": "teaching",
            "content": "提示 A",
            "interactionId": "support:1",
        },
        {
            "seq": 2,
            "actor": "student",
            "kind": "guided_answer",
            "content": [{"questionId": "q1", "question": "Q", "answer": "A"}],
            "interactionId": "support:1",
            "replyTo": "support:1",
        },
        {
            "seq": 3,
            "actor": "teacher",
            "kind": "teaching",
            "content": "提示 B",
            "interactionId": "support:2",
        },
    ]
    result = _truncate_by_interaction(events, max_interactions=2)
    # 完整交互组：support:1 组（teaching + guided_answer）和 support:2 组（teaching）
    assert [event["interactionId"] for event in result] == [
        "support:1",
        "support:1",
        "support:2",
    ]


def test_truncate_zero_or_empty_returns_empty() -> None:
    assert _truncate_by_interaction([], 5) == []
    assert _truncate_by_interaction(
        [{"seq": 0, "actor": "student", "kind": "explanation", "content": "x"}], 0
    ) == []
