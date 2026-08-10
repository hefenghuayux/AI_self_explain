from typing import Literal

from pydantic import ConfigDict, Field

from app.schemas.ai_evaluation import Completeness, Correctness, ErrorEvidence
from app.schemas.question import QuestionSchema, RequiredText, to_camel_case

GeneratedTeachingAction = Literal[
    "ASK_FOCUSED_QUESTION",
    "GIVE_HINT",
    "GIVE_CORRECTION",
    "CORRECT_AND_ASK",
]
LearningPhase = Literal["FIRST_ROUND", "REEXPLANATION_AFTER_SOLUTION"]
SupportBudgetState = Literal[
    "EARLY",
    "NORMAL",
    "APPROACHING_LIMIT",
    "FINAL_ALLOWED_SUPPORT",
    "EXHAUSTED",
]
ProgressState = Literal["MAKING_PROGRESS", "NO_NEW_PROGRESS"]
SolutionExposure = Literal["FORBIDDEN", "ALREADY_SHOWN_DO_NOT_REPEAT"]


class TeachingSchema(QuestionSchema):
    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


class TeachingTask(TeachingSchema):
    question_content: RequiredText
    standard_answer: RequiredText
    rubric_points: list[RequiredText]
    common_errors: list[RequiredText]
    alternative_solutions: list[RequiredText]
    layered_hints: list[RequiredText]
    guided_questions: list[RequiredText]
    full_solution: RequiredText
    current_student_text: RequiredText


class EvaluationContext(TeachingSchema):
    correctness: Correctness
    completeness: Completeness
    covered_points: list[RequiredText]
    missing_points: list[RequiredText]
    error_evidence: list[ErrorEvidence]


class LearningProgress(TeachingSchema):
    already_covered_points: list[RequiredText]
    newly_covered_points: list[RequiredText]
    target_rubric_point: RequiredText | None
    target_error_evidence: ErrorEvidence | None


class RecentAttempt(TeachingSchema):
    student_text_excerpt: RequiredText
    new_covered_points: list[RequiredText]


class GivenQuestion(TeachingSchema):
    question_excerpt: RequiredText
    answer_excerpt: RequiredText | None
    answered: bool


class GivenSupport(TeachingSchema):
    support_type: GeneratedTeachingAction
    content_excerpt: RequiredText
    questions: list[GivenQuestion]


class TeachingHistory(TeachingSchema):
    recent_attempts: list[RecentAttempt] = Field(max_length=2)
    already_given_supports: list[GivenSupport] = Field(max_length=9)
    history_truncated: bool


class TeachingMetadata(TeachingSchema):
    learning_phase: LearningPhase
    support_budget_state: SupportBudgetState
    progress_state: ProgressState
    solution_exposure: SolutionExposure


class InstructionFromRules(TeachingSchema):
    allowed_action: GeneratedTeachingAction
    target_rubric_point: RequiredText | None
    do_not_repeat: list[RequiredText]
    do_not_reveal: list[RequiredText]
    response_goal: RequiredText


class TeachingContext(TeachingSchema):
    schema_version: Literal["1.0"] = "1.0"
    task: TeachingTask
    latest_evaluation: EvaluationContext
    learning_progress: LearningProgress
    teaching_history: TeachingHistory
    teaching_metadata: TeachingMetadata
    instruction_from_rules: InstructionFromRules
    long_term_evidence: None = None
