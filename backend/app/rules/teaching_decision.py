from dataclasses import dataclass

from app.core.config import Settings
from app.models.session import Session
from app.rules.teaching_cycle import completion_type_for, support_limit_for, update_coverage
from app.schemas.ai_evaluation import AIEvaluationOutput
from app.schemas.teaching import GeneratedTeachingAction

COUNTED_SUPPORT_TYPES = frozenset({"GIVE_HINT", "GIVE_CORRECTION", "CORRECT_AND_ASK"})


@dataclass(frozen=True)
class CoverageResult:
    current_round: list[str]
    all_rounds: list[str]
    newly_covered: list[str]
    no_progress_count: int
    reset_help_request_count: bool


@dataclass(frozen=True)
class TeachingDecision:
    allowed_action: GeneratedTeachingAction | None
    should_generate: bool
    next_status: str | None
    next_flow_stage: str | None
    completion_type: str | None
    need_human_reason: str | None
    expose_solution: bool
    support_count_round_override: int | None
    coverage: CoverageResult


def decide_teaching(
    *,
    evaluation: AIEvaluationOutput,
    session: Session,
    settings: Settings,
    evaluation_mode: str = "FULL_RUBRIC",
) -> TeachingDecision:
    coverage = _coverage_result(evaluation=evaluation, session=session)
    if evaluation.correctness == "CORRECT" and evaluation.completeness == "COMPLETE":
        return _decision(
            session=session,
            coverage=coverage,
            next_status="COMPLETED",
            next_flow_stage="WAIT_STUDENT_ACTION",
            completion_type=completion_type_for(
                solution_exposed=session.solution_exposed,
                round_number=session.round,
                support_count_total=session.support_count_total,
            ),
        )

    if evaluation_mode != "FULL_RUBRIC":
        return _decision(
            session=session,
            coverage=coverage,
            next_status="IN_PROGRESS",
            next_flow_stage="WAIT_STUDENT_ACTION",
            need_human_reason="题目未配置评分点，无法生成可审计的针对性支持",
        )

    action = _action_for(evaluation)
    if action in COUNTED_SUPPORT_TYPES:
        support_limit = support_limit_for(round_number=session.round, settings=settings)
        if session.support_count_round + 1 >= support_limit:
            return _decision(
                session=session,
                coverage=coverage,
                next_status="STOPPED_LIMIT" if session.round == 2 else "IN_PROGRESS",
                next_flow_stage="SHOWING_FULL_SOLUTION",
                expose_solution=True,
                support_count_round_override=support_limit,
            )

    return _decision(
        session=session,
        coverage=coverage,
        allowed_action=action,
        should_generate=True,
    )


def _action_for(evaluation: AIEvaluationOutput) -> GeneratedTeachingAction:
    if not evaluation.has_progress:
        return "GIVE_HINT"
    if evaluation.correctness == "WRONG":
        return "GIVE_CORRECTION"
    return "ASK_FOCUSED_QUESTION"


def _coverage_result(
    *, evaluation: AIEvaluationOutput, session: Session
) -> CoverageResult:
    newly_covered = [
        point
        for point in evaluation.covered_points
        if point not in set(session.covered_points_current_round)
    ]
    current_round, all_rounds, _ = update_coverage(
        covered_points=evaluation.covered_points,
        covered_points_current_round=session.covered_points_current_round,
        covered_points_all=session.covered_points_all,
        no_progress_count=session.no_progress_count,
    )
    return CoverageResult(
        current_round=current_round,
        all_rounds=all_rounds,
        newly_covered=newly_covered,
        no_progress_count=0 if evaluation.has_progress else session.no_progress_count + 1,
        reset_help_request_count=False,
    )


def _decision(
    *,
    session: Session,
    coverage: CoverageResult,
    allowed_action: GeneratedTeachingAction | None = None,
    should_generate: bool = False,
    next_status: str | None = None,
    next_flow_stage: str | None = None,
    completion_type: str | None = None,
    need_human_reason: str | None = None,
    expose_solution: bool = False,
    support_count_round_override: int | None = None,
) -> TeachingDecision:
    return TeachingDecision(
        allowed_action=allowed_action,
        should_generate=should_generate,
        next_status=next_status,
        next_flow_stage=next_flow_stage,
        completion_type=completion_type,
        need_human_reason=need_human_reason,
        expose_solution=expose_solution,
        support_count_round_override=support_count_round_override,
        coverage=coverage,
    )
