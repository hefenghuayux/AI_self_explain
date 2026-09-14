import pytest

from app.models.session import Session
from app.rules.teaching_decision import decide_teaching
from app.schemas.merged import MergedModelOutput


def merged_output(
    correctness: str,
    completeness: str,
    *,
    covered_points: list[str] | None = None,
    need_human_reason: str | None = None,
    teaching_action: str | None = None,
    questions: list[dict[str, str]] | None = None,
) -> MergedModelOutput:
    return MergedModelOutput.model_validate(
        {
            "correctness": correctness,
            "completeness": completeness,
            "coveredPoints": covered_points or [],
            "errorEvidence": [],
            "needHumanReason": need_human_reason,
            "teachingAction": teaching_action,
            "content": "教学正文。" if teaching_action is not None else None,
            "questions": questions or [],
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
        ("CORRECT", "INCOMPLETE", "GIVE_HINT"),
        ("WRONG", "INCOMPLETE", "GIVE_HINT"),
    ],
)
def test_teaching_action_from_model_flows_through_to_generation(
    settings, correctness: str, completeness: str, action: str
) -> None:
    decision = decide_teaching(
        merged_output=merged_output(
            correctness,
            completeness,
            covered_points=["评分点 A"],
            teaching_action=action,
        ),
        session=session(),
        settings=settings,
    )

    assert decision.allowed_action == action
    assert decision.should_generate is True
    assert decision.coverage.newly_covered == ["评分点 A"]


def test_complete_decision_is_deterministic_and_skips_generation(settings) -> None:
    decision = decide_teaching(
        merged_output=merged_output(
            "CORRECT", "COMPLETE", covered_points=["评分点 A"]
        ),
        session=session(support_count_total=1),
        settings=settings,
    )

    assert decision.allowed_action is None
    assert decision.should_generate is False
    assert decision.next_status == "COMPLETED"
    assert decision.completion_type == "WITH_SUPPORT"


@pytest.mark.parametrize("evaluation_mode", ["BASIC", "AI_GENERAL"])
def test_non_rubric_correct_evaluation_completes_without_teaching(
    settings, evaluation_mode: str
) -> None:
    decision = decide_teaching(
        merged_output=merged_output("CORRECT", "INCOMPLETE"),
        session=session(),
        settings=settings,
        evaluation_mode=evaluation_mode,
    )

    assert decision.next_status == "COMPLETED"
    assert decision.should_generate is False


def test_non_rubric_wrong_evaluation_requests_human_review(settings) -> None:
    decision = decide_teaching(
        merged_output=merged_output("WRONG", "INCOMPLETE"),
        session=session(),
        settings=settings,
        evaluation_mode="BASIC",
    )

    assert decision.next_status == "IN_PROGRESS"
    assert decision.should_generate is False
    assert decision.need_human_reason == "题目未配置评分点，无法生成可审计的针对性支持"


def test_uncertain_decision_preserves_coverage_and_requests_human(settings) -> None:
    current_session = session(
        covered_points_current_round=["评分点 A"],
        covered_points_all=["评分点 A"],
        no_progress_count=1,
    )
    decision = decide_teaching(
        merged_output=merged_output(
            "UNCERTAIN",
            "INCOMPLETE",
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
        merged_output=merged_output(
            "WRONG", "COMPLETE", teaching_action="GIVE_CORRECTION"
        ),
        session=session(round=round_number, support_count_round=limit - 1),
        settings=settings,
    )

    assert decision.should_generate is False
    assert decision.expose_solution is True
    assert decision.next_status == expected_status
    assert decision.next_flow_stage == "SHOWING_FULL_SOLUTION"
    assert decision.support_count_round_override == limit


def test_non_terminal_merged_output_requires_teaching_action(settings) -> None:
    with pytest.raises(ValueError, match="缺少 teachingAction"):
        decide_teaching(
            merged_output=merged_output("WRONG", "INCOMPLETE"),
            session=session(),
            settings=settings,
        )