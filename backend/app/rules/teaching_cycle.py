from app.core.config import Settings

COUNTED_SUPPORT_TYPES = frozenset({"GIVE_HINT", "GIVE_CORRECTION", "CORRECT_AND_ASK"})
# 第一轮自讲结束后，满足任一条件才进入掌握度核验。
MASTERY_CHECK_MIN_SUPPORT_COUNT = 3
MASTERY_CHECK_AFTER_SOLUTION_MIN_SUPPORT_COUNT = 2


def support_limit_reached(*, support_count_round: int, settings: Settings) -> bool:
    """判断下一次支持请求是否已经超出上限。

    `support_count_round` 是“本轮已经实际发送的支持次数”。上限语义是实际
    最多发送 N 次，所以计数达到上限时，下一次请求不再生成支持内容，直接
    展示完整解析。
    """
    return support_count_round >= settings.first_round_support_limit


def support_limit_for(*, settings: Settings) -> int:
    return settings.first_round_support_limit


def needs_mastery_check(*, support_count_round: int, solution_exposed: bool) -> bool:
    """按有效支持数和是否已展示完整解析，确定性地判断是否需要核验。

    支持数 <= 1 时优先跳过核验；支持数为 2 且未展示完整解析时也直接结束本题。
    """
    if support_count_round >= MASTERY_CHECK_MIN_SUPPORT_COUNT:
        return True
    return (
        solution_exposed
        and support_count_round >= MASTERY_CHECK_AFTER_SOLUTION_MIN_SUPPORT_COUNT
    )


def completion_type_for(*, support_count_round: int, mastery_check_completed: bool) -> str:
    """完成方式只由会话事实决定：是否做过核验、本轮是否发送过支持。"""
    if mastery_check_completed:
        return "AFTER_MASTERY_CHECK"
    if support_count_round > 0:
        return "WITH_SUPPORT"
    return "INDEPENDENT"
