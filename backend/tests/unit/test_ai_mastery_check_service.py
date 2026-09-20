import json

from app.models.question import Question
from app.models.session import Session
from app.schemas.mastery_check import MasteryCheckAnswer
from app.services.ai_mastery_check import (
    MasteryCheckEvidence,
    MasteryCheckQuestionInput,
    _render_assessment_prompt,
    _render_generation_prompt,
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


def evidence() -> MasteryCheckEvidence:
    return MasteryCheckEvidence(
        evaluation_id=12,
        main_reason="知识应用问题",
        judge_reason="学生写出了计算方向，但没有说明依据。",
        student_text="我把两个数合起来。",
    )


def test_generation_prompt_has_five_layer_structure() -> None:
    request = _render_generation_prompt(
        question=question(),
        session=Session(round=1, support_count_round=4),
        evidence=evidence(),
        validation_errors=[],
        model="test-model",
        prompt_version="mastery-v1",
    )

    assert request.schema_version == "1.1"
    assert request.purpose == "AI_MASTERY_CHECK"
    messages = request.transport.messages
    assert len(messages) == 5

    # [0] system：全局共享前缀
    assert messages[0].role == "system"
    assert "后端模型组件" in messages[0].content

    # [1] user：题目上下文
    assert messages[1].role == "user"
    msg1 = json.loads(messages[1].content)
    assert msg1["questionContent"] == "计算 1 + 1。"

    # [2] user：共享历史，未传 progress_context 时为空
    assert messages[2].role == "user"
    assert json.loads(messages[2].content) == {"events": []}

    # [3] user：任务指令来自 generate_mastery_check.md
    assert messages[3].role == "user"
    assert "掌握度核验问题生成器" in messages[3].content
    assert "evidenceRefs" in messages[3].content

    # [4] user：本轮任务数据只含证据，不含业务计数
    assert messages[4].role == "user"
    msg4 = json.loads(messages[4].content)
    assert msg4["mainReason"] == "知识应用问题"
    assert msg4["judgeReason"] == "学生写出了计算方向，但没有说明依据。"
    assert msg4["studentText"] == "我把两个数合起来。"
    assert "round" not in msg4
    assert "supportCountRound" not in msg4

    # blocks：证据进入 userInput，session_context 不携带轮次与计数
    assert request.blocks.user_input == {
        "mainReason": "知识应用问题",
        "judgeReason": "学生写出了计算方向，但没有说明依据。",
        "studentText": "我把两个数合起来。",
    }
    assert request.blocks.session_context == {"taskType": "MASTERY_CHECK"}
    assert request.blocks.retry_context == {"validationErrors": []}
    assert request.privacy.contains_student_content is True
    assert request.privacy.contains_answer_material is True
    assert request.privacy.contains_memory is False


def test_generation_prompt_omits_session_counts_from_transport() -> None:
    request = _render_generation_prompt(
        question=question(),
        session=Session(round=2, support_count_round=3),
        evidence=evidence(),
        validation_errors=["核验问题数量必须在 1 到 2 之间"],
        model="test-model",
        prompt_version="mastery-v1",
    )

    for message in request.transport.messages:
        assert '"round"' not in message.content
        assert '"supportCountRound"' not in message.content
    current_data = json.loads(request.transport.messages[4].content)
    assert current_data["validationErrors"] == ["核验问题数量必须在 1 到 2 之间"]


def test_assessment_prompt_carries_questions_answers_and_evidence() -> None:
    questions = [
        MasteryCheckQuestionInput(
            question_id="mc1",
            question="你在配方这一步依据的是什么？",
            evidence_refs=[
                {
                    "source": "EVALUATION",
                    "sourceId": "12",
                    "quote": "学生写出了配方步骤，但未说明依据。",
                }
            ],
        )
    ]
    answers = [MasteryCheckAnswer(question_id="mc1", answer="依据完全平方公式。")]

    request = _render_assessment_prompt(
        question=question(),
        session=Session(round=1, support_count_round=4),
        questions=questions,
        answers=answers,
        validation_errors=[],
        model="test-model",
        prompt_version="mastery-v1",
    )

    assert request.purpose == "MASTERY_CHECK_ASSESSMENT"
    assert len(request.transport.messages) == 5
    assert "掌握度核验评估器" in request.transport.messages[3].content

    current_data = json.loads(request.transport.messages[4].content)
    assert current_data["questions"] == [
        {
            "id": "mc1",
            "question": "你在配方这一步依据的是什么？",
            "evidenceRefs": [
                {
                    "source": "EVALUATION",
                    "sourceId": "12",
                    "quote": "学生写出了配方步骤，但未说明依据。",
                }
            ],
        }
    ]
    assert current_data["answers"] == [
        {"question_id": "mc1", "answer": "依据完全平方公式。"}
    ]
    assert "round" not in current_data
    assert request.blocks.session_context == {"taskType": "MASTERY_CHECK"}
