import pytest

from app.models.session import Session
from app.rules.teaching_decision import decide_teaching
from app.schemas.ai_evaluation import AIEvaluationOutput


def evaluation(
    correctness: str,
    completeness: str,
    *,
    covered_points: list[str] | None = None,
    missing_points: list[str] | None = None,
    need_human_reason: str | None = None,
) -> AIEvaluationOutput:
    return AIEvaluationOutput.model_validate(
        {
            "correctness": correctness,
            "completeness": completeness,
            "coveredPoints": covered_points or [],
            "missingPoints": missing_points or [],
            "errorEvidence": [],
            "confidence": 1,
            "needHumanReason": need_human_reason,
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
        "covered_points_current_round": [],
        "covered_points_all": [],
    }
    values.update(updates)
    return Session(**values)


@pytest.mark.parametrize(
    ("correctness", "completeness", "action"),
    [
        ("CORRECT", "INCOMPLETE", "ASK_FOCUSED_QUESTION"),
        ("WRONG", "COMPLETE", "GIVE_CORRECTION"),
        ("WRONG", "INCOMPLETE", "CORRECT_AND_ASK"),
    ],
)
def test_evaluation_mapping_selects_generated_action(
    settings, correctness: str, completeness: str, action: str
) -> None:
    decision = decide_teaching(
        evaluation=evaluation(
            correctness,
            completeness,
            covered_points=["评分点 A"],
            missing_points=["评分点 B"],
        ),
        session=session(),
        settings=settings,
    )

    assert decision.allowed_action == action
    assert decision.should_generate is True
    assert decision.coverage.newly_covered == ["评分点 A"]
    assert decision.metadata.progress_state == "MAKING_PROGRESS"


def test_complete_decision_is_deterministic_and_skips_generation(settings) -> None:
    decision = decide_teaching(
        evaluation=evaluation("CORRECT", "COMPLETE", covered_points=["评分点 A"]),
        session=session(support_count_total=1),
        settings=settings,
    )

    assert decision.allowed_action is None
    assert decision.should_generate is False
    assert decision.next_status == "COMPLETED"
    assert decision.completion_type == "WITH_SUPPORT"


def test_uncertain_decision_preserves_coverage_and_requests_human(settings) -> None:
    current_session = session(
        covered_points_current_round=["评分点 A"],
        covered_points_all=["评分点 A"],
        no_progress_count=1,
    )
    decision = decide_teaching(
        evaluation=evaluation(
            "UNCERTAIN",
            "INCOMPLETE",
            missing_points=["评分点 B"],
            need_human_reason="材料不足",
        ),
        session=current_session,
        settings=settings,
    )

    assert decision.should_generate is False
    assert decision.next_flow_stage == "WAIT_STUDENT_ACTION"
    assert decision.need_human_reason == "材料不足"
    assert decision.coverage.current_round == ["评分点 A"]
    assert decision.coverage.no_progress_count == 1


def test_no_progress_upgrades_focused_question_to_counted_hint(settings) -> None:
    decision = decide_teaching(
        evaluation=evaluation("CORRECT", "INCOMPLETE", missing_points=["评分点 B"]),
        session=session(no_progress_count=settings.no_progress_limit - 1),
        settings=settings,
    )

    assert decision.allowed_action == "GIVE_HINT"
    assert decision.coverage.no_progress_count == settings.no_progress_limit


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
