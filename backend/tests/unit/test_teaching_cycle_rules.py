from app.rules.teaching_cycle import (
    completion_type_for,
    decide_evaluation,
    support_limit_reached,
    update_coverage,
)


def test_update_coverage_tracks_new_points_only_for_current_round() -> None:
    current, all_points, no_progress = update_coverage(
        covered_points=["评分点 A"],
        covered_points_current_round=["评分点 A"],
        covered_points_all=["旧轮评分点"],
        no_progress_count=1,
    )

    assert current == ["评分点 A"]
    assert all_points == ["旧轮评分点", "评分点 A"]
    assert no_progress == 2


def test_no_progress_upgrades_focused_question_to_counted_hint(settings) -> None:
    decision = decide_evaluation(
        next_action="ASK_FOCUSED_QUESTION",
        no_progress_count=settings.no_progress_limit,
        settings=settings,
        solution_exposed=False,
        round_number=1,
        support_count_total=0,
        need_human_reason=None,
    )

    assert decision.action == "GIVE_HINT"


def test_support_limits_are_derived_from_settings(settings) -> None:
    assert not support_limit_reached(
        round_number=1,
        support_count_round=settings.first_round_support_limit - 2,
        settings=settings,
    )
    assert support_limit_reached(
        round_number=1,
        support_count_round=settings.first_round_support_limit - 1,
        settings=settings,
    )
    assert support_limit_reached(
        round_number=2,
        support_count_round=settings.second_round_support_limit - 1,
        settings=settings,
    )


def test_completion_type_uses_only_deterministic_session_facts() -> None:
    assert completion_type_for(
        solution_exposed=False, round_number=1, support_count_total=0
    ) == "INDEPENDENT"
    assert completion_type_for(
        solution_exposed=False, round_number=1, support_count_total=1
    ) == "WITH_SUPPORT"
    assert completion_type_for(
        solution_exposed=True, round_number=2, support_count_total=0
    ) == "AFTER_SOLUTION"
