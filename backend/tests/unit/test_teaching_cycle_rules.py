import pytest

from app.rules.teaching_cycle import (
    completion_type_for,
    needs_mastery_check,
    support_limit_for,
    support_limit_reached,
)


def test_support_limit_allows_the_configured_number_of_supports(settings) -> None:
    limit = settings.first_round_support_limit

    assert not support_limit_reached(support_count_round=0, settings=settings)
    assert not support_limit_reached(support_count_round=limit - 1, settings=settings)
    # 计数等于上限表示“上限次支持已经发送”，下一次请求才触发完整解析。
    assert support_limit_reached(support_count_round=limit, settings=settings)
    assert support_limit_reached(support_count_round=limit + 1, settings=settings)
    assert support_limit_for(settings=settings) == limit


@pytest.mark.parametrize(
    ("support_count_round", "expected"),
    [
        (0, False),
        (1, False),
        (2, True),
        (3, True),
        (6, True),
    ],
)
def test_mastery_check_trigger_depends_only_on_support_count(
    support_count_round: int, expected: bool
) -> None:
    assert needs_mastery_check(support_count_round=support_count_round) is expected


def test_completion_type_uses_only_deterministic_session_facts() -> None:
    assert completion_type_for(
        support_count_round=0, mastery_check_completed=False
    ) == "INDEPENDENT"
    assert completion_type_for(
        support_count_round=1, mastery_check_completed=False
    ) == "WITH_SUPPORT"
    assert completion_type_for(
        support_count_round=2, mastery_check_completed=True
    ) == "AFTER_MASTERY_CHECK"
    assert completion_type_for(
        support_count_round=6, mastery_check_completed=True
    ) == "AFTER_MASTERY_CHECK"
