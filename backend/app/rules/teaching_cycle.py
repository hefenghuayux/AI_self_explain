from dataclasses import dataclass

from app.core.config import Settings

SUPPORT_TYPES = frozenset({"GIVE_HINT", "GIVE_CORRECTION", "CORRECT_AND_ASK"})


@dataclass(frozen=True)
class EvaluationDecision:
    action: str
    next_status: str | None = None
    next_flow_stage: str | None = None
    completion_type: str | None = None
    need_human_reason: str | None = None


def update_coverage(
    *,
    covered_points: list[str],
    covered_points_current_round: list[str],
    covered_points_all: list[str],
    no_progress_count: int,
) -> tuple[list[str], list[str], int]:
    current_round_points = set(covered_points_current_round)
    new_points = set(covered_points) - current_round_points
    next_no_progress_count = 0 if new_points else no_progress_count + 1
    return (
        _append_unique(covered_points_current_round, covered_points),
        _append_unique(covered_points_all, covered_points),
        next_no_progress_count,
    )


def decide_evaluation(
    *,
    next_action: str,
    no_progress_count: int,
    settings: Settings,
    solution_exposed: bool,
    round_number: int,
    support_count_total: int,
    need_human_reason: str | None,
) -> EvaluationDecision:
    if next_action == "COMPLETE":
        completion_type = completion_type_for(
            solution_exposed=solution_exposed,
            round_number=round_number,
            support_count_total=support_count_total,
        )
        return EvaluationDecision(
            action="COMPLETE",
            next_status="COMPLETED",
            next_flow_stage="WAIT_STUDENT_ACTION",
            completion_type=completion_type,
        )
    if next_action == "NEED_HUMAN":
        if need_human_reason is None:
            raise ValueError("NEED_HUMAN 评价缺少具体原因")
        return EvaluationDecision(
            action="NEED_HUMAN",
            next_status="NEED_HUMAN",
            next_flow_stage="WAIT_STUDENT_ACTION",
            need_human_reason=need_human_reason,
        )
    if next_action == "ASK_FOCUSED_QUESTION" and no_progress_count >= settings.no_progress_limit:
        return EvaluationDecision(action="GIVE_HINT")
    return EvaluationDecision(action=next_action)


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


def _append_unique(existing: list[str], incoming: list[str]) -> list[str]:
    result = list(existing)
    known = set(existing)
    for point in incoming:
        if point not in known:
            result.append(point)
            known.add(point)
    return result
