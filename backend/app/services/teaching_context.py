from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from app.models.ai_evaluation import AIEvaluation
from app.models.explanation_attempt import ExplanationAttempt
from app.models.question import Question
from app.models.session import Session
from app.models.support_event import SupportEvent
from app.rules.teaching_decision import TeachingDecision
from app.schemas.ai_evaluation import AIEvaluationOutput
from app.schemas.teaching import (
    EvaluationContext,
    GivenQuestion,
    GivenSupport,
    InstructionFromRules,
    LearningProgress,
    RecentAttempt,
    TeachingContext,
    TeachingHistory,
    TeachingTask,
)

RESPONSE_GOALS = {
    "ASK_FOCUSED_QUESTION": "ASK_ONE_FOCUSED_QUESTION",
    "GIVE_HINT": "GIVE_ONE_LOCAL_HINT",
    "GIVE_CORRECTION": "CORRECT_IDENTIFIED_ERROR",
    "CORRECT_AND_ASK": "CORRECT_ERROR_AND_ASK_ONE_QUESTION",
}


class TeachingContextService:
    def __init__(self, database_session: DatabaseSession) -> None:
        self.database_session = database_session

    def build(
        self,
        *,
        question: Question,
        session: Session,
        attempt: ExplanationAttempt,
        evaluation: AIEvaluationOutput,
        decision: TeachingDecision,
    ) -> TeachingContext:
        if not decision.should_generate or decision.allowed_action is None:
            raise ValueError("当前确定性决策不允许调用教学模型")
        if attempt.confirmed_text is None:
            raise ValueError("构造 TeachingContext 时缺少确认文本")

        target_point = _target_rubric_point(question.rubric_points, evaluation.covered_points)
        if decision.allowed_action in {"ASK_FOCUSED_QUESTION", "CORRECT_AND_ASK"}:
            if target_point is None:
                raise ValueError("需要追问的教学动作缺少目标评分点")

        history = self._history(session.id, attempt.id)
        return TeachingContext(
            task=TeachingTask(
                question_content=question.question_content,
                standard_answer=question.standard_answer,
                rubric_points=question.rubric_points,
                common_errors=question.common_errors,
                alternative_solutions=question.alternative_solutions,
                layered_hints=question.layered_hints,
                guided_questions=question.guided_questions,
                full_solution=question.full_solution,
                current_student_text=attempt.confirmed_text,
            ),
            latest_evaluation=EvaluationContext(
                correctness=evaluation.correctness,
                completeness=evaluation.completeness,
                covered_points=evaluation.covered_points,
                missing_points=[
                    point for point in question.rubric_points if point not in set(evaluation.covered_points)
                ],
                error_evidence=evaluation.error_evidence,
            ),
            learning_progress=LearningProgress(
                already_covered_points=list(session.covered_points_current_round),
                newly_covered_points=decision.coverage.newly_covered,
                target_rubric_point=target_point,
                target_error_evidence=(
                    evaluation.error_evidence[0] if evaluation.error_evidence else None
                ),
            ),
            teaching_history=history,
            teaching_metadata=decision.metadata,
            instruction_from_rules=InstructionFromRules(
                allowed_action=decision.allowed_action,
                target_rubric_point=target_point,
                do_not_repeat=[item.content_excerpt for item in history.already_given_supports],
                do_not_reveal=[
                    "DO_NOT_REVEAL_FULL_SOLUTION",
                    "DO_NOT_QUOTE_STANDARD_ANSWER",
                    "DO_NOT_ANSWER_FUTURE_RUBRIC_POINTS",
                ],
                response_goal=RESPONSE_GOALS[decision.allowed_action],
            ),
        )

    def _history(self, session_id: int, current_attempt_id: int) -> TeachingHistory:
        attempts = list(
            self.database_session.scalars(
                select(ExplanationAttempt)
                .where(
                    ExplanationAttempt.session_id == session_id,
                    ExplanationAttempt.id < current_attempt_id,
                    ExplanationAttempt.confirmed_text.is_not(None),
                )
                .order_by(ExplanationAttempt.id)
            )
        )
        evaluations = list(
            self.database_session.scalars(
                select(AIEvaluation)
                .where(
                    AIEvaluation.session_id == session_id,
                    AIEvaluation.validation_status == "VALID",
                    AIEvaluation.attempt_id < current_attempt_id,
                )
                .order_by(AIEvaluation.id)
            )
        )
        evaluations_by_attempt = {item.attempt_id: item for item in evaluations}
        seen_by_round: dict[int, set[str]] = {}
        recent_attempts: list[RecentAttempt] = []
        for prior_attempt in attempts:
            prior_evaluation = evaluations_by_attempt.get(prior_attempt.id)
            covered = prior_evaluation.covered_points if prior_evaluation is not None else []
            seen = seen_by_round.setdefault(prior_attempt.round, set())
            new_covered = [point for point in covered or [] if point not in seen]
            seen.update(covered or [])
            recent_attempts.append(
                RecentAttempt(
                    student_text_excerpt=_excerpt(prior_attempt.confirmed_text or "", 400),
                    new_covered_points=new_covered,
                )
            )

        supports = list(
            self.database_session.scalars(
                select(SupportEvent)
                .where(SupportEvent.session_id == session_id, SupportEvent.status == "VALID")
                .order_by(SupportEvent.id)
            )
        )
        selected_attempts = recent_attempts[-2:]
        selected_supports = supports[-9:]
        return TeachingHistory(
            recent_attempts=selected_attempts,
            already_given_supports=[_given_support(item) for item in selected_supports],
            history_truncated=(
                len(recent_attempts) > len(selected_attempts)
                or len(supports) > len(selected_supports)
            ),
        )


def _target_rubric_point(rubric_points: list[str], covered_points: list[str]) -> str | None:
    covered = set(covered_points)
    return next((point for point in rubric_points if point not in covered), None)


def _given_support(support: SupportEvent) -> GivenSupport:
    answers = {
        str(item["question_id"]): str(item["answer"])
        for item in support.guided_answers or []
        if "question_id" in item and "answer" in item
    }
    questions = [
        GivenQuestion(
            question_excerpt=_excerpt(str(item["question"]), 160),
            answer_excerpt=(
                _excerpt(answers[str(item["id"])], 300)
                if str(item["id"]) in answers
                else None
            ),
            answered=str(item["id"]) in answers,
        )
        for item in support.guided_questions or []
        if "id" in item and "question" in item
    ]
    return GivenSupport(
        support_type=support.support_type,
        content_excerpt=_excerpt(support.content, 300),
        questions=questions,
    )


def _excerpt(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("教学历史摘录不能为空")
    if len(normalized) <= limit:
        return normalized
    head_length = (limit - 3) // 2
    tail_length = limit - 3 - head_length
    return normalized[:head_length] + "..." + normalized[-tail_length:]
