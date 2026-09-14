from app.models.question import Question
from app.models.session import Session
from app.models.support_event import SupportEvent
from app.schemas.support import GuidedAnswer
from app.services.ai_support import (
    _render_answer_assessment_prompt,
    _render_support_prompt,
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
        covered_points_current_round=["正确计算加法"],
    )


def test_support_request_snapshot_separates_main_draft_and_doubt() -> None:
    request = _render_support_prompt(
        question=question(),
        session=session(),
        main_draft="我知道要把两个数相加。",
        doubt_text="为什么这里使用加法？",
        force_current_step=False,
        validation_errors=["action 不合法"],
        model="test-model",
        prompt_version="support-v1",
    )

    assert request.purpose == "AI_SUPPORT"
    assert request.blocks.user_input == {
        "mainDraft": "我知道要把两个数相加。",
        "doubtText": "为什么这里使用加法？",
        "forceCurrentStepAnswer": False,
    }
    assert request.blocks.retry_context == {"validationErrors": ["action 不合法"]}
    assert request.blocks.memory_context is None
    payload = request.transport_payload()
    assert payload["model"] == "test-model"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["messages"] == [
        msg.model_dump(mode="json") for msg in request.transport.messages
    ]
    assert "为什么这里使用加法？" in request.transport.messages[0].content
    assert "逐字引用一句" in request.transport.messages[0].content


def test_guided_answer_snapshot_separates_questions_and_answers() -> None:
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

    assert request.purpose == "GUIDED_ANSWER_ASSESSMENT"
    assert request.blocks.user_input["mainDraft"] == "我已经把两个数放在一起。"
    assert request.blocks.user_input["questions"] == support.guided_questions
    assert request.blocks.user_input["answers"] == [
        {"question_id": "q1", "answer": "等于 2"}
    ]
    assert request.privacy.contains_student_content is True
    assert request.privacy.contains_answer_material is True
    assert request.privacy.contains_memory is False
    assert "逐字引用一句" in request.transport.messages[0].content
