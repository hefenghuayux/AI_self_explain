from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DatabaseSession

from app.models.ai_evaluation import AIEvaluation
from app.models.base import Base
from app.models.explanation_attempt import ExplanationAttempt
from app.models.question import Question
from app.models.session import Session
from app.models.support_event import SupportEvent
from app.rules.teaching_decision import decide_teaching
from app.schemas.ai_evaluation import AIEvaluationOutput
from app.services.teaching_context import TeachingContextService


def test_teaching_context_is_bounded_and_excludes_raw_state(settings) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with DatabaseSession(engine) as database_session:
            question = Question(
                question_content="1+1 等于多少？",
                standard_answer="2",
                rubric_points=["说明加法", "得到结果 2"],
                common_errors=["结果写成 3"],
                alternative_solutions=["数手指"],
                layered_hints=["想一想两个一"],
                guided_questions=["两个一合起来是多少？"],
                full_solution="1+1=2",
            )
            current_session = Session(
                question_id=1,
                status="IN_PROGRESS",
                flow_stage="AI_EVALUATING",
                round=1,
                support_count_round=1,
                support_count_total=1,
                no_progress_count=0,
                no_progress_help_request_count=0,
                solution_exposed=False,
                covered_points_current_round=["说明加法"],
                covered_points_all=["说明加法"],
                current_draft="",
                last_support_draft="",
                version=2,
            )
            database_session.add_all([question, current_session])
            database_session.flush()
            prior_attempts: list[ExplanationAttempt] = []
            for index in range(3):
                prior_attempt = ExplanationAttempt(
                    session_id=current_session.id,
                    round=1,
                    input_mode="TEXT",
                    confirmed_text=f"历史尝试 {index}",
                )
                database_session.add(prior_attempt)
                database_session.flush()
                prior_attempts.append(prior_attempt)
                database_session.add(
                    AIEvaluation(
                        session_id=current_session.id,
                        attempt_id=prior_attempt.id,
                        correctness="CORRECT",
                        completeness="INCOMPLETE",
                        covered_points=["说明加法"],
                        missing_points=["得到结果 2"],
                        error_evidence=[],
                        confidence=1,
                        need_human_reason=None,
                        prompt_version="test",
                        model_provider="test",
                        model_name="test",
                        raw_response="{}",
                        validation_status="VALID",
                        validation_errors=[],
                        request_duration_ms=1,
                    )
                )
            for index in range(10):
                database_session.add(
                    SupportEvent(
                        session_id=current_session.id,
                        support_type="GIVE_HINT",
                        round=1,
                        status="VALID",
                        content=f"历史提示 {index}",
                        support_kind="EVALUATION",
                    )
                )
            current_attempt = ExplanationAttempt(
                session_id=current_session.id,
                round=1,
                input_mode="TEXT",
                confirmed_text="两个一相加，但我没说结果。",
            )
            database_session.add(current_attempt)
            database_session.commit()

            evaluation = AIEvaluationOutput.model_validate(
                {
                    "correctness": "CORRECT",
                    "completeness": "INCOMPLETE",
                    "coveredPoints": ["说明加法"],
                    "missingPoints": ["得到结果 2"],
                    "errorEvidence": [],
                    "confidence": 1,
                    "needHumanReason": None,
                }
            )
            decision = decide_teaching(
                evaluation=evaluation,
                session=current_session,
                settings=settings,
            )
            context = TeachingContextService(database_session).build(
                question=question,
                session=current_session,
                attempt=current_attempt,
                evaluation=evaluation,
                decision=decision,
            )

            payload = context.model_dump(by_alias=True)
            assert context.learning_progress.target_rubric_point == "得到结果 2"
            assert len(context.teaching_history.recent_attempts) == 2
            assert len(context.teaching_history.already_given_supports) == 9
            assert context.teaching_history.history_truncated is True
            assert context.long_term_evidence is None
            serialized = str(payload)
            assert "supportCountRound" not in serialized
            assert "flowStage" not in serialized
            assert "version" not in serialized
    finally:
        engine.dispose()


def test_context_rejects_non_generation_decision(settings) -> None:
    evaluation = AIEvaluationOutput.model_validate(
        {
            "correctness": "CORRECT",
            "completeness": "COMPLETE",
            "coveredPoints": ["评分点"],
            "missingPoints": [],
            "errorEvidence": [],
            "confidence": 1,
            "needHumanReason": None,
        }
    )
    current_session = Session(
        round=1,
        support_count_round=0,
        support_count_total=0,
        no_progress_count=0,
        no_progress_help_request_count=0,
        solution_exposed=False,
        covered_points_current_round=[],
        covered_points_all=[],
    )
    decision = decide_teaching(
        evaluation=evaluation,
        session=current_session,
        settings=settings,
    )

    try:
        TeachingContextService(None).build(
            question=Question(),
            session=current_session,
            attempt=ExplanationAttempt(confirmed_text="完整答案"),
            evaluation=evaluation,
            decision=decision,
        )
    except ValueError as error:
        assert str(error) == "当前确定性决策不允许调用教学模型"
    else:
        raise AssertionError("非生成决策必须拒绝构造 TeachingContext")
