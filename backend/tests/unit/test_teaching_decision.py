import pytest

from app.models.session import Session
from app.rules.teaching_decision import decide_teaching
from app.schemas.ai_evaluation import AIEvaluationOutput

RUBRIC_POINTS = ["评分点 A", "评分点 B"]


def evaluation(
    correctness: str,
    completeness: str,
    *,
    has_progress: bool = True,
) -> AIEvaluationOutput:
    terminal = correctness == "CORRECT" and completeness == "COMPLETE"
    return AIEvaluationOutput.model_validate(
        {
            "correctness": correctness,
            "completeness": completeness,
            "hasProgress": has_progress,
            "mainReason": None if terminal else "知识应用问题",
            "otherReasons": [],
            "judgeReason": None if terminal else "学生尚未完成当前推理。",
        }
    )


def session(**updates: object) -> Session:
    values: dict[str, object] = {
        "round": 1,
        "support_count_round": 0,
        "support_count_total": 0,
        "no_progress_count": 0,
        "no_progress_help_request_count": 0,
        "solution_exposed": False,
    }
    values.update(updates)
    return Session(**values)


@pytest.mark.parametrize(
    ("correctness", "completeness", "has_progress", "expected_action"),
    [
        ("CORRECT", "INCOMPLETE", True, "ASK_FOCUSED_QUESTION"),
        ("WRONG", "COMPLETE", True, "GIVE_CORRECTION"),
        ("WRONG", "INCOMPLETE", True, "GIVE_CORRECTION"),
        ("CORRECT", "INCOMPLETE", False, "GIVE_HINT"),
        ("WRONG", "INCOMPLETE", False, "GIVE_HINT"),
    ],
)
def test_teaching_action_is_selected_by_deterministic_priority(
    settings,
    correctness: str,
    completeness: str,
    has_progress: bool,
    expected_action: str,
) -> None:
    decision = decide_teaching(
        evaluation=evaluation(
            correctness,
            completeness,
            has_progress=has_progress,
        ),
        session=session(),
        settings=settings,
    )

    assert decision.allowed_action == expected_action
    assert decision.should_generate is True


def test_complete_decision_is_deterministic_and_skips_generation(settings) -> None:
    decision = decide_teaching(
        evaluation=evaluation("CORRECT", "COMPLETE"),
        session=session(support_count_total=1),
        settings=settings,
    )

    assert decision.allowed_action is None
    assert decision.should_generate is False
    assert decision.next_status == "COMPLETED"
    assert decision.completion_type == "WITH_SUPPORT"


@pytest.mark.parametrize("evaluation_mode", ["BASIC", "AI_GENERAL"])
def test_non_rubric_complete_evaluation_completes_without_teaching(
    settings, evaluation_mode: str
) -> None:
    decision = decide_teaching(
        evaluation=evaluation("CORRECT", "COMPLETE"),
        session=session(),
        settings=settings,
        evaluation_mode=evaluation_mode,
    )

    assert decision.next_status == "COMPLETED"
    assert decision.should_generate is False


def test_non_rubric_non_terminal_evaluation_requests_human_review(settings) -> None:
    decision = decide_teaching(
        evaluation=evaluation("WRONG", "INCOMPLETE"),
        session=session(),
        settings=settings,
        evaluation_mode="BASIC",
    )

    assert decision.next_status == "IN_PROGRESS"
    assert decision.should_generate is False
    assert decision.need_human_reason == "题目未配置评分点，无法生成可审计的针对性支持"


def test_has_progress_controls_no_progress_count(settings) -> None:
    progressed = decide_teaching(
        evaluation=evaluation("CORRECT", "INCOMPLETE", has_progress=True),
        session=session(no_progress_count=2),
        settings=settings,
    )
    stalled = decide_teaching(
        evaluation=evaluation("CORRECT", "INCOMPLETE", has_progress=False),
        session=session(no_progress_count=2),
        settings=settings,
    )

    assert progressed.coverage.no_progress_count == 0
    assert stalled.coverage.no_progress_count == 3


@pytest.mark.parametrize(
    ("round_number", "expected_status"),
    [(1, "IN_PROGRESS"), (2, "STOPPED_LIMIT")],
)
def test_counted_action_hits_limit_before_generation(
    settings, round_number: int, expected_status: str
) -> None:
    limit = (
        settings.first_round_support_limit
        if round_number == 1
        else settings.second_round_support_limit
    )
    decision = decide_teaching(
        evaluation=evaluation("WRONG", "COMPLETE"),
        session=session(round=round_number, support_count_round=limit - 1),
        settings=settings,
    )

    assert decision.should_generate is False
    assert decision.expose_solution is True
    assert decision.next_status == expected_status
    assert decision.next_flow_stage == "SHOWING_FULL_SOLUTION"
    assert decision.support_count_round_override == limit
