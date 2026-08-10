from dataclasses import dataclass

from app.core.config import Settings
from app.models.session import Session
from app.rules.teaching_cycle import completion_type_for, support_limit_for, update_coverage
from app.schemas.ai_evaluation import AIEvaluationOutput
from app.schemas.teaching import (
    GeneratedTeachingAction,
    LearningPhase,
    ProgressState,
    SolutionExposure,
    SupportBudgetState,
    TeachingMetadata,
)

INITIAL_ACTIONS: dict[tuple[str, str], str] = {
    ("CORRECT", "COMPLETE"): "COMPLETE",
    ("CORRECT", "INCOMPLETE"): "ASK_FOCUSED_QUESTION",
    ("WRONG", "COMPLETE"): "GIVE_CORRECTION",
    ("WRONG", "INCOMPLETE"): "CORRECT_AND_ASK",
    ("UNCERTAIN", "COMPLETE"): "NEED_HUMAN",
    ("UNCERTAIN", "INCOMPLETE"): "NEED_HUMAN",
}
COUNTED_GENERATED_ACTIONS = frozenset({"GIVE_HINT", "GIVE_CORRECTION", "CORRECT_AND_ASK"})


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
    metadata: TeachingMetadata


def decide_teaching(
    *, evaluation: AIEvaluationOutput, session: Session, settings: Settings
) -> TeachingDecision:
    coverage = _coverage_result(evaluation=evaluation, session=session)
    action = INITIAL_ACTIONS[(evaluation.correctness, evaluation.completeness)]

    if (
        action == "ASK_FOCUSED_QUESTION"
        and coverage.no_progress_count >= settings.no_progress_limit
    ):
        action = "GIVE_HINT"

    if action == "COMPLETE":
        return _decision(
            session=session,
            settings=settings,
            coverage=coverage,
            next_status="COMPLETED",
            next_flow_stage="WAIT_STUDENT_ACTION",
            completion_type=completion_type_for(
                solution_exposed=session.solution_exposed,
                round_number=session.round,
                support_count_total=session.support_count_total,
            ),
        )

    if action == "NEED_HUMAN":
        if evaluation.need_human_reason is None:
            raise ValueError("UNCERTAIN 评价缺少人工处理原因")
        return _decision(
            session=session,
            settings=settings,
            coverage=coverage,
            next_status="IN_PROGRESS",
            next_flow_stage="WAIT_STUDENT_ACTION",
            need_human_reason=evaluation.need_human_reason,
        )

    if action in COUNTED_GENERATED_ACTIONS:
        support_limit = support_limit_for(round_number=session.round, settings=settings)
        if session.support_count_round + 1 >= support_limit:
            return _decision(
                session=session,
                settings=settings,
                coverage=coverage,
                next_status="STOPPED_LIMIT" if session.round == 2 else "IN_PROGRESS",
                next_flow_stage="SHOWING_FULL_SOLUTION",
                expose_solution=True,
                support_count_round_override=support_limit,
            )

    return _decision(
        session=session,
        settings=settings,
        coverage=coverage,
        allowed_action=action,
        should_generate=True,
    )


def _coverage_result(*, evaluation: AIEvaluationOutput, session: Session) -> CoverageResult:
    if evaluation.correctness == "UNCERTAIN":
        return CoverageResult(
            current_round=list(session.covered_points_current_round),
            all_rounds=list(session.covered_points_all),
            newly_covered=[],
            no_progress_count=session.no_progress_count,
            reset_help_request_count=False,
        )
    newly_covered = [
        point
        for point in evaluation.covered_points
        if point not in set(session.covered_points_current_round)
    ]
    current_round, all_rounds, no_progress_count = update_coverage(
        covered_points=evaluation.covered_points,
        covered_points_current_round=session.covered_points_current_round,
        covered_points_all=session.covered_points_all,
        no_progress_count=session.no_progress_count,
    )
    return CoverageResult(
        current_round=current_round,
        all_rounds=all_rounds,
        newly_covered=newly_covered,
        no_progress_count=no_progress_count,
        reset_help_request_count=bool(newly_covered),
    )


def _decision(
    *,
    session: Session,
    settings: Settings,
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
        metadata=_metadata(session=session, settings=settings, coverage=coverage),
    )


def _metadata(
    *, session: Session, settings: Settings, coverage: CoverageResult
) -> TeachingMetadata:
    remaining = support_limit_for(round_number=session.round, settings=settings) - (
        session.support_count_round
    )
    if remaining <= 0:
        budget_state: SupportBudgetState = "EXHAUSTED"
    elif remaining == 1:
        budget_state = "FINAL_ALLOWED_SUPPORT"
    elif remaining == 2:
        budget_state = "APPROACHING_LIMIT"
    elif session.support_count_round == 0:
        budget_state = "EARLY"
    else:
        budget_state = "NORMAL"
    learning_phase: LearningPhase = (
        "REEXPLANATION_AFTER_SOLUTION"
        if session.round == 2 or session.solution_exposed
        else "FIRST_ROUND"
    )
    progress_state: ProgressState = (
        "MAKING_PROGRESS" if coverage.newly_covered else "NO_NEW_PROGRESS"
    )
    solution_exposure: SolutionExposure = (
        "ALREADY_SHOWN_DO_NOT_REPEAT" if session.solution_exposed else "FORBIDDEN"
    )
    return TeachingMetadata(
        learning_phase=learning_phase,
        support_budget_state=budget_state,
        progress_state=progress_state,
        solution_exposure=solution_exposure,
    )
