from app.rules.teaching_cycle import (
    completion_type_for,
    support_limit_reached,
)


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