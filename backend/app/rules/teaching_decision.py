from dataclasses import dataclass

from app.core.config import Settings
from app.models.session import Session
from app.rules.session_lifecycle import (
    FLOW_STAGE_WAIT_MASTERY_CHECK,
    FLOW_STAGE_WAIT_STUDENT_ACTION,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_NEEDS_REVIEW,
)
from app.rules.teaching_cycle import (
    completion_type_for,
    needs_mastery_check,
    support_limit_for,
)
from app.schemas.ai_evaluation import AIEvaluationOutput
from app.schemas.teaching import GeneratedTeachingAction

COUNTED_SUPPORT_TYPES = frozenset({"GIVE_HINT", "GIVE_CORRECTION", "CORRECT_AND_ASK"})


@dataclass(frozen=True)
class CoverageResult:
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
    start_mastery_check: bool
    coverage: CoverageResult


def decide_teaching(
    *,
    evaluation: AIEvaluationOutput,
    session: Session,
    settings: Settings,
    evaluation_mode: str = "FULL_RUBRIC",
) -> TeachingDecision:
    coverage = CoverageResult(
        no_progress_count=0 if evaluation.has_progress else session.no_progress_count + 1,
        reset_help_request_count=False,
    )
    if evaluation.correctness == "CORRECT" and evaluation.completeness == "COMPLETE":
        return _first_round_end_decision(session=session, coverage=coverage)

    if evaluation_mode != "FULL_RUBRIC":
        return _decision(
            coverage=coverage,
            next_status=STATUS_IN_PROGRESS,
            next_flow_stage=FLOW_STAGE_WAIT_STUDENT_ACTION,
            need_human_reason="题目未配置评分点，无法生成可审计的针对性支持",
        )

    action = _action_for(evaluation)
    if action in COUNTED_SUPPORT_TYPES:
        support_limit = support_limit_for(settings=settings)
        if session.support_count_round >= support_limit:
            # 支持数已达上限：第 7 次请求不再生成支持，直接展示完整解析。
            return _decision(
                coverage=coverage,
                next_status=STATUS_IN_PROGRESS,
                next_flow_stage="SHOWING_FULL_SOLUTION",
                expose_solution=True,
                support_count_round_override=support_limit,
            )

    return _decision(
        coverage=coverage,
        allowed_action=action,
        should_generate=True,
    )


def decide_mastery_check_outcome(*, all_passed: bool) -> TeachingDecision:
    """核验结果只由“是否所有问题都通过”决定，AI 不参与状态判断。"""
    return _decision(
        coverage=CoverageResult(no_progress_count=0, reset_help_request_count=False),
        next_status=STATUS_COMPLETED if all_passed else STATUS_NEEDS_REVIEW,
        next_flow_stage=FLOW_STAGE_WAIT_STUDENT_ACTION,
        completion_type="AFTER_MASTERY_CHECK",
    )


def _first_round_end_decision(
    *, session: Session, coverage: CoverageResult
) -> TeachingDecision:
    """第一轮结束：按有效支持数和是否展示完整解析决定是否进入核验。"""
    if needs_mastery_check(
        support_count_round=session.support_count_round,
        solution_exposed=session.solution_exposed,
    ):
        return _decision(
            coverage=coverage,
            next_status=STATUS_IN_PROGRESS,
            next_flow_stage=FLOW_STAGE_WAIT_MASTERY_CHECK,
            start_mastery_check=True,
        )
    return _decision(
        coverage=coverage,
        next_status=STATUS_COMPLETED,
        next_flow_stage=FLOW_STAGE_WAIT_STUDENT_ACTION,
        completion_type=completion_type_for(
            support_count_round=session.support_count_round,
            mastery_check_completed=False,
        ),
    )


def _action_for(evaluation: AIEvaluationOutput) -> GeneratedTeachingAction:
    if not evaluation.has_progress:
        return "GIVE_HINT"
    if evaluation.correctness == "WRONG":
        return "GIVE_CORRECTION"
    return "ASK_FOCUSED_QUESTION"


def _decision(
    *,
    coverage: CoverageResult,
    allowed_action: GeneratedTeachingAction | None = None,
    should_generate: bool = False,
    next_status: str | None = None,
    next_flow_stage: str | None = None,
    completion_type: str | None = None,
    need_human_reason: str | None = None,
    expose_solution: bool = False,
    support_count_round_override: int | None = None,
    start_mastery_check: bool = False,
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
        start_mastery_check=start_mastery_check,
        coverage=coverage,
    )
