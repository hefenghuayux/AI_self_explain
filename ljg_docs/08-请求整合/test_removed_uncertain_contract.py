import pytest
from pydantic import ValidationError

from app.schemas.ai_evaluation import AIEvaluationOutput
from app.schemas.merged import MergedModelOutput, validate_merged_output
from app.schemas.support import GuidedAnswerAssessmentOutput, SupportRequestOutput
from app.services.ai_support import _validate_answer_assessment, _validate_support_request


def test_evaluation_rejects_uncertain_and_removed_human_reason() -> None:
    with pytest.raises(ValidationError):
        AIEvaluationOutput.model_validate(
            {
                "correctness": "UNCERTAIN",
                "completeness": "INCOMPLETE",
                "coveredPoints": [],
                "errorEvidence": [],
            }
        )

    with pytest.raises(ValidationError):
        AIEvaluationOutput.model_validate(
            {
                "correctness": "WRONG",
                "completeness": "INCOMPLETE",
                "coveredPoints": [],
                "errorEvidence": [],
                "needHumanReason": None,
            }
        )


def test_non_terminal_evaluation_requires_a_specific_reason() -> None:
    output = MergedModelOutput.model_validate(
        {
            "correctness": "WRONG",
            "completeness": "INCOMPLETE",
            "coveredPoints": [],
            "errorEvidence": [],
            "hasProgress": False,
            "mainReason": None,
            "otherReasons": [],
            "judgeReason": None,
            "teachingAction": "GIVE_HINT",
            "content": "先检查当前条件。",
            "questions": [],
        }
    )

    errors = validate_merged_output(output, ["评分点"], "我不会")

    assert "非终态评价必须返回具体 main_reason" in errors
    assert "非终态评价必须返回 judge_reason" in errors


def test_terminal_evaluation_uses_null_reason_fields() -> None:
    output = MergedModelOutput.model_validate(
        {
            "correctness": "CORRECT",
            "completeness": "COMPLETE",
            "coveredPoints": [1],
            "errorEvidence": [],
            "hasProgress": True,
            "mainReason": None,
            "otherReasons": [],
            "judgeReason": None,
            "teachingAction": None,
            "content": None,
            "questions": [],
        }
    )

    assert validate_merged_output(output, ["评分点"], "完整解释") == []


def test_support_null_reason_is_limited_to_non_diagnostic_results() -> None:
    refusal = SupportRequestOutput.model_validate(
        {
            "action": "REFUSE_FULL_SOLUTION",
            "main_reason": None,
            "other_reasons": [],
            "judge_reason": None,
            "content": "只能提供局部帮助。",
            "questions": [],
        }
    )
    guided = SupportRequestOutput.model_validate(
        {
            "action": "GUIDED_QUESTIONS",
            "main_reason": None,
            "other_reasons": [],
            "judge_reason": None,
            "content": "先回答这个问题。",
            "questions": [{"id": "q1", "question": "已知条件是什么？"}],
        }
    )

    assert _validate_support_request(refusal) == []
    assert _validate_support_request(guided) == ["非拒答支持必须返回具体困难原因和判断依据"]


def test_all_correct_guided_answers_have_no_difficulty_reason() -> None:
    output = GuidedAnswerAssessmentOutput.model_validate(
        {
            "results": [{"questionId": "q1", "result": "CORRECT"}],
            "main_reason": None,
            "other_reasons": [],
            "judge_reason": None,
            "content": "可以继续整合。",
        }
    )
    support_event = type("Support", (), {"guided_questions": [{"id": "q1"}]})()

    assert _validate_answer_assessment(output, support_event) == []
