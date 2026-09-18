import json

import pytest

from app.models.question import Question
from app.models.session import Session
from app.models.support_event import SupportEvent
from app.schemas.support import GuidedAnswer, SupportRequestOutput
from app.services.ai_support import (
    MAX_GUIDED_QUESTIONS,
    _render_answer_assessment_prompt,
    _render_support_prompt,
    _validate_support_request,
)


def question() -> Question:
    return Question(
        question_content="计算 1 + 1。",
        standard_answer="2",
        rubric_points=["正确计算加法", "得出结果 2"],
        common_errors=["把结果写成 3"],
        alternative_solutions=["使用实物计数"],
        layered_hints=["先合并数量"],
        guided_questions=["两个 1 合起来是多少？"],
        full_solution="1 加 1 等于 2。",
    )


def session() -> Session:
    return Session(
        round=1,
        support_count_round=2,
    )


def test_support_request_has_five_layer_structure() -> None:
    request = _render_support_prompt(
        question=question(),
        session=session(),
        main_draft="我知道要把两个数相加。",
        doubt_text="为什么这里使用加法？",
        validation_errors=["action 不合法"],
        model="test-model",
        prompt_version="support-v1",
    )

    assert request.schema_version == "1.1"
    assert request.purpose == "AI_SUPPORT"
    messages = request.transport.messages
    assert len(messages) == 5

    # [0] system: shared system
    assert messages[0].role == "system"
    assert "后端模型组件" in messages[0].content
    assert "原因定义" in messages[0].content

    # [1] user: question context (stable, no session state)
    assert messages[1].role == "user"
    msg1 = json.loads(messages[1].content)
    assert msg1["questionContent"] == "计算 1 + 1。"
    assert "round" not in msg1
    assert "supportCountRound" not in msg1

    # [2] user: shared history (default empty when progress_context not provided)
    assert messages[2].role == "user"
    msg2 = json.loads(messages[2].content)
    assert msg2 == {"events": []}

    # [3] user: task instructions
    assert messages[3].role == "user"
    assert "疑问支持生成器" in messages[3].content
    assert "HELP" in messages[3].content
    assert "REFUSE_FULL_SOLUTION" in messages[3].content
    assert "validationErrors" in messages[3].content
    assert "{{CONTEXT_JSON}}" not in messages[3].content

    # [4] user: current round data
    assert messages[4].role == "user"
    msg4 = json.loads(messages[4].content)
    assert msg4["mainDraft"] == "我知道要把两个数相加。"
    assert msg4["doubtText"] == "为什么这里使用加法？"
    assert msg4["validationErrors"] == ["action 不合法"]

    # blocks preserved
    assert request.blocks.system_instructions is not None
    assert "后端模型组件" in request.blocks.system_instructions
    assert request.blocks.task_instructions is not None
    assert "疑问支持生成器" in request.blocks.task_instructions
    assert request.blocks.user_input == {
        "mainDraft": "我知道要把两个数相加。",
        "doubtText": "为什么这里使用加法？",
    }
    assert request.blocks.retry_context == {"validationErrors": ["action 不合法"]}
    assert request.blocks.memory_context is None
    assert request.blocks.question_context is not None
    assert request.blocks.question_context["questionContent"] == "计算 1 + 1。"
    assert request.blocks.session_context["taskType"] == "HELP"

    # transport payload snapshot
    payload = request.transport_payload()
    assert payload["model"] == "test-model"
    assert payload["response_format"] == {"type": "json_object"}
    assert len(payload["messages"]) == 5
    assert payload["messages"] == [
        msg.model_dump(mode="json") for msg in messages
    ]


def test_guided_answer_has_five_layer_structure() -> None:
    support = SupportEvent(
        main_draft="我已经把两个数放在一起。",
        guided_questions=[
            {"id": "q1", "question": "两个 1 合起来是多少？"},
        ],
    )
    request = _render_answer_assessment_prompt(
        question=question(),
        session=session(),
        support_event=support,
        answers=[GuidedAnswer(question_id="q1", answer="等于 2")],
        validation_errors=[],
        model="test-model",
        prompt_version="assessment-v1",
    )

    assert request.schema_version == "1.1"
    assert request.purpose == "GUIDED_ANSWER_ASSESSMENT"
    messages = request.transport.messages
    assert len(messages) == 5

    # [0] system
    assert messages[0].role == "system"
    assert "后端模型组件" in messages[0].content

    # [1] user: question context
    assert messages[1].role == "user"
    msg1 = json.loads(messages[1].content)
    assert msg1["questionContent"] == "计算 1 + 1。"
    assert "round" not in msg1

    # [2] user: shared history (default empty when progress_context not provided)
    assert messages[2].role == "user"
    msg2 = json.loads(messages[2].content)
    assert msg2 == {"events": []}

    # [3] user: task instructions
    assert messages[3].role == "user"
    assert "子问题作答评估器" in messages[3].content
    assert "GUIDED_ANSWER" in messages[3].content

    # [4] user: current round data
    assert messages[4].role == "user"
    msg4 = json.loads(messages[4].content)
    assert msg4["mainDraft"] == "我已经把两个数放在一起。"
    assert msg4["questions"] == support.guided_questions
    assert msg4["answers"] == [{"question_id": "q1", "answer": "等于 2"}]
    assert "validationErrors" not in msg4  # empty list → omitted

    # blocks
    assert request.blocks.user_input["mainDraft"] == "我已经把两个数放在一起。"
    assert request.blocks.user_input["questions"] == support.guided_questions
    assert request.blocks.user_input["answers"] == [
        {"question_id": "q1", "answer": "等于 2"}
    ]
    assert request.privacy.contains_student_content is True
    assert request.privacy.contains_answer_material is True
    assert request.privacy.contains_memory is False


def test_support_progress_context_passed_through() -> None:
    """传入 progress_context 时 messages[2] 包含对应 events。"""
    progress_context = {
        "events": [
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
                "content": "旧提示",
                "interactionId": "support:1",
            },
        ]
    }
    request = _render_support_prompt(
        question=question(),
        session=session(),
        main_draft="新草稿",
        doubt_text=None,
        validation_errors=[],
        model="test-model",
        prompt_version="support-v1",
        progress_context=progress_context,
    )
    msg2 = json.loads(request.transport.messages[2].content)
    assert msg2 == progress_context
    assert len(msg2["events"]) == 2
    assert msg2["events"][0]["actor"] == "student"


def support_output(question_count: int) -> SupportRequestOutput:
    return SupportRequestOutput(
        action="GUIDED_QUESTIONS",
        content="先判断开口方向。",
        questions=[
            {"id": f"q{index}", "question": f"第 {index} 个子问题"}
            for index in range(1, question_count + 1)
        ],
    )


@pytest.mark.parametrize("question_count", [1, MAX_GUIDED_QUESTIONS])
def test_support_request_accepts_guided_questions_within_limit(question_count: int) -> None:
    assert _validate_support_request(support_output(question_count)) == []


@pytest.mark.parametrize("question_count", [0, MAX_GUIDED_QUESTIONS + 1, 12])
def test_support_request_rejects_guided_questions_outside_limit(question_count: int) -> None:
    errors = _validate_support_request(support_output(question_count))

    assert errors == [f"GUIDED_QUESTIONS 的子问题数量必须在 1 到 {MAX_GUIDED_QUESTIONS} 之间"]


def test_support_request_rejects_duplicate_question_ids() -> None:
    output = SupportRequestOutput(
        action="GUIDED_QUESTIONS",
        content="先判断开口方向。",
        questions=[
            {"id": "q1", "question": "第一个"},
            {"id": "q1", "question": "重复标识"},
        ],
    )

    assert _validate_support_request(output) == ["questions 的 id 不能重复"]


def test_non_guided_action_rejects_questions() -> None:
    output = SupportRequestOutput(
        action="SIMPLE_DOUBT_ANSWER",
        content="这里用的是加法交换律。",
        questions=[{"id": "q1", "question": "多余的子问题"}],
    )

    assert _validate_support_request(output) == ["非子问题动作不能提供 questions"]
