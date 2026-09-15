from dataclasses import dataclass

from app.core.config import Settings
from app.models.session import Session
from app.rules.teaching_cycle import completion_type_for, support_limit_for, update_coverage
from app.schemas.ai_evaluation import AIEvaluationOutput
from app.schemas.merged import MergedModelOutput
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
    merged_output: MergedModelOutput,
    session: Session,
    settings: Settings,
    evaluation_mode: str = "FULL_RUBRIC",
) -> TeachingDecision:
    """根据合并输出的评价字段和模型给出的教学动作做确定性决策。

    教学动作（追问/提示/纠错）由模型在输出中通过 teachingAction 给出；
    本轮是否新增评分点仍由后端按 coveredPoints 与
    coveredPointsCurrentRound 的差集确定，只用于覆盖记录和审计。
    后端确定性负责：COMPLETED / 支持上限阻断。
    """
    evaluation = _as_evaluation_output(merged_output)
    if evaluation_mode != "FULL_RUBRIC":
        return _decide_without_rubric(
            evaluation=evaluation, session=session, settings=settings
        )

    coverage = _coverage_result(evaluation=evaluation, session=session)

    if merged_output.correctness == "CORRECT" and merged_output.completeness == "COMPLETE":
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

    action = merged_output.teaching_action
    if action is None:
        raise ValueError("非终态合并输出缺少 teachingAction")

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


def _decide_without_rubric(
    *, evaluation: AIEvaluationOutput, session: Session, settings: Settings
) -> TeachingDecision:
    coverage = _coverage_result(evaluation=evaluation, session=session)
    if evaluation.correctness == "CORRECT":
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

    return _decision(
        session=session,
        coverage=coverage,
        next_status="IN_PROGRESS",
        next_flow_stage="WAIT_STUDENT_ACTION",
        need_human_reason="题目未配置评分点，无法生成可审计的针对性支持",
    )


def _coverage_result(
    *, evaluation: AIEvaluationOutput, session: Session
) -> CoverageResult:
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


def _as_evaluation_output(merged_output: MergedModelOutput) -> AIEvaluationOutput:
    return AIEvaluationOutput(
        correctness=merged_output.correctness,
        completeness=merged_output.completeness,
        covered_points=merged_output.covered_points,
        error_evidence=merged_output.error_evidence,
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
