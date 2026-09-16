from app.core.config import Settings

COUNTED_SUPPORT_TYPES = frozenset({"GIVE_HINT", "GIVE_CORRECTION", "CORRECT_AND_ASK"})


def support_limit_reached(
    *, round_number: int, support_count_round: int, settings: Settings
) -> bool:
    limit = support_limit_for(round_number=round_number, settings=settings)
    return support_count_round + 1 >= limit


def support_limit_for(*, round_number: int, settings: Settings) -> int:
    if round_number == 1:
        return settings.first_round_support_limit
    if round_number == 2:
        return settings.second_round_support_limit
    raise ValueError(f"不支持的教学轮次：{round_number}")


def completion_type_for(
    *, solution_exposed: bool, round_number: int, support_count_total: int
) -> str:
    if solution_exposed and round_number == 2:
        return "AFTER_SOLUTION"
    if support_count_total > 0:
        return "WITH_SUPPORT"
    return "INDEPENDENT"



