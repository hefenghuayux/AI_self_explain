import json
from contextlib import contextmanager
from pathlib import Path

import httpx
from alembic.config import Config
from conftest import authenticated_test_client
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from alembic import command
from app.models.ai_evaluation import AIEvaluation
from app.models.explanation_attempt import ExplanationAttempt
from app.models.external_call_record import ExternalCallRecord
from app.models.question import Question as QuestionModel
from app.models.session import Session as SessionModel
from app.models.session_event import SessionEvent
from app.models.state_transition_event import StateTransitionEvent
from app.schemas.mastery_check import MasteryCheckAnswer
from app.schemas.model_request_snapshot import ModelRequestSnapshot
from app.services.ai_evaluation import AIModelClient, AIModelResponse
from app.services.ai_mastery_check import AIMasteryCheckService, MasteryCheckQuestionInput
from app.services.event_store import EventStore

EVALUATION_RUN_ID = "run_session_{session_id}_attempt_{attempt_id}"
VALID_EVALUATION_OUTPUT = {
    "correctness": "CORRECT",
    "completeness": "INCOMPLETE",
    "hasProgress": True,
    "mainReason": "知识应用问题",
    "otherReasons": [],
    "judgeReason": "学生写出了计算方向，但没有说明依据。",
}
VALID_QUESTIONS = {
    "questions": [
        {
            "id": "mc1",
            "question": "你在合并数量这一步依据的是什么？",
            "evidenceRefs": [
                {
                    "source": "EVALUATION",
                    "sourceId": "1",
                    "quote": "学生写出了计算方向，但没有说明依据。",
                }
            ],
        }
    ]
}
VALID_ASSESSMENT = {
    "results": [
        {"questionId": "mc1", "passed": False, "basis": "学生只复述了支持内容，未说明依据。"}
    ]
}


def migrate_database(settings, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    alembic_config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.upgrade(alembic_config, "head")


def prepare_client(settings, monkeypatch) -> TestClient:
    migrate_database(settings, monkeypatch)
    return authenticated_test_client(settings)


def seed_valid_evaluation(settings) -> tuple[int, int, int, int]:
    """写入一条有效评价及其模型响应事件。

    返回 (session_id, question_id, attempt_id, evaluation_id)。
    """
    engine = create_engine(settings.database_url)
    try:
        with OrmSession(engine) as database_session:
            question = QuestionModel(
                question_content="计算 1 + 1。",
                standard_answer="2",
                rubric_points=["正确计算加法", "得出结果 2"],
            )
            database_session.add(question)
            database_session.flush()
            session = SessionModel(
                question_id=question.id,
                status="IN_PROGRESS",
                flow_stage="WAIT_STUDENT_ACTION",
                round=1,
                support_count_round=3,
                support_count_total=3,
                no_progress_count=0,
                solution_exposed=False,
                current_draft="我把两个数合起来。",
                last_support_draft="我把两个数合起来。",
                version=1,
            )
            database_session.add(session)
            database_session.flush()
            attempt = ExplanationAttempt(
                session_id=session.id,
                round=1,
                input_mode="TEXT",
                confirmed_text="我把两个数合起来。",
            )
            database_session.add(attempt)
            database_session.flush()
            evaluation = AIEvaluation(
                session_id=session.id,
                attempt_id=attempt.id,
                correctness="CORRECT",
                completeness="INCOMPLETE",
                evaluation_mode="FULL_RUBRIC",
                prompt_version="test-v1",
                model_provider="test-ai",
                model_name="test-ai-model",
                raw_response=json.dumps(VALID_EVALUATION_OUTPUT, ensure_ascii=False),
                validation_status="VALID",
                validation_errors=[],
                request_duration_ms=10,
            )
            database_session.add(evaluation)
            database_session.commit()
            EventStore(database_session).append(
                session_id=session.id,
                event_type="model.responded",
                run_id=EVALUATION_RUN_ID.format(
                    session_id=session.id, attempt_id=attempt.id
                ),
                data={
                    "output": VALID_EVALUATION_OUTPUT,
                    "rawContent": json.dumps(VALID_EVALUATION_OUTPUT, ensure_ascii=False),
                    "validation": "valid",
                    "durationMs": 10,
                },
            )
            database_session.commit()
            return session.id, question.id, attempt.id, evaluation.id
    finally:
        engine.dispose()


@contextmanager
def mastery_service(settings):
    """打开一个指向测试库的服务实例，调用方负责使用与断言。"""
    engine = create_engine(settings.database_url)
    database_session = OrmSession(engine)
    http_client = httpx.Client()
    try:
        yield database_session, AIMasteryCheckService(database_session, settings, http_client)
    finally:
        http_client.close()
        database_session.close()
        engine.dispose()


def read_session(settings, session_id: int) -> SessionModel:
    engine = create_engine(settings.database_url)
    try:
        with OrmSession(engine) as database_session:
            return database_session.get(SessionModel, session_id)
    finally:
        engine.dispose()


def read_trigger_types(settings, session_id: int) -> list[str]:
    engine = create_engine(settings.database_url)
    try:
        with OrmSession(engine) as database_session:
            return list(
                database_session.scalars(
                    select(StateTransitionEvent.trigger_type).where(
                        StateTransitionEvent.session_id == session_id
                    )
                )
            )
    finally:
        engine.dispose()


def read_mastery_calls(settings, session_id: int) -> list[ExternalCallRecord]:
    engine = create_engine(settings.database_url)
    try:
        with OrmSession(engine) as database_session:
            return list(
                database_session.scalars(
                    select(ExternalCallRecord).where(
                        ExternalCallRecord.session_id == session_id,
                        ExternalCallRecord.call_type.in_(
                            ("AI_MASTERY_CHECK", "MASTERY_CHECK_ASSESSMENT")
                        ),
                    )
                )
            )
    finally:
        engine.dispose()


def stub_mastery_evaluation(monkeypatch, content: str) -> None:
    def fake_evaluate(self, request: ModelRequestSnapshot) -> AIModelResponse:
        return AIModelResponse(raw_response='{"choices": []}', content=content, duration_ms=5)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)


def load_entities(database_session, session_id: int, question_id: int, attempt_id: int):
    return (
        database_session.get(SessionModel, session_id),
        database_session.get(QuestionModel, question_id),
        database_session.get(ExplanationAttempt, attempt_id),
    )


def test_illegal_question_count_requests_human_review(settings, monkeypatch) -> None:
    prepare_client(settings, monkeypatch)
    session_id, question_id, attempt_id, evaluation_id = seed_valid_evaluation(settings)
    monkeypatch.setattr("app.services.ai_mastery_check.time.sleep", lambda _: None)
    stub_mastery_evaluation(
        monkeypatch,
        json.dumps({"questions": [VALID_QUESTIONS["questions"][0]] * 3}, ensure_ascii=False),
    )

    with mastery_service(settings) as (database_session, service):
        session, question, _ = load_entities(
            database_session, session_id, question_id, attempt_id
        )
        result = service.generate_questions(question=question, session=session)

    assert result is None
    session = read_session(settings, session_id)
    assert session.need_human_reason is not None
    assert "重试次数内仍不合法" in session.need_human_reason
    assert session.support_count_round == 3
    assert session.status == "IN_PROGRESS"
    assert "AI_MASTERY_CHECK_SCHEMA_RETRY_EXHAUSTED" in read_trigger_types(settings, session_id)
    calls = read_mastery_calls(settings, session_id)
    assert calls and calls[-1].validation_status == "INVALID"


def test_valid_questions_are_recorded_as_validated_output(settings, monkeypatch) -> None:
    prepare_client(settings, monkeypatch)
    session_id, question_id, attempt_id, evaluation_id = seed_valid_evaluation(settings)
    stub_mastery_evaluation(monkeypatch, json.dumps(VALID_QUESTIONS, ensure_ascii=False))

    with mastery_service(settings) as (database_session, service):
        session, question, _ = load_entities(
            database_session, session_id, question_id, attempt_id
        )
        result = service.generate_questions(question=question, session=session)

    assert result is not None
    assert [item.id for item in result.questions] == ["mc1"]
    calls = read_mastery_calls(settings, session_id)
    assert calls and calls[-1].validation_status == "VALID"

    engine = create_engine(settings.database_url)
    try:
        with OrmSession(engine) as database_session:
            run_id = f"run_session_{session_id}_mastery_check_AI_MASTERY_CHECK_1"
            responded = list(
                database_session.scalars(
                    select(SessionEvent).where(
                        SessionEvent.session_id == session_id,
                        SessionEvent.run_id == run_id,
                        SessionEvent.event_type == "model.responded",
                    )
                )
            )
            assert responded and responded[-1].data["validation"] == "valid"
            assert responded[-1].data["output"]["questions"][0]["id"] == "mc1"
    finally:
        engine.dispose()


def test_answer_assessment_rejects_mismatched_question_ids(settings, monkeypatch) -> None:
    prepare_client(settings, monkeypatch)
    session_id, question_id, attempt_id, evaluation_id = seed_valid_evaluation(settings)
    monkeypatch.setattr("app.services.ai_mastery_check.time.sleep", lambda _: None)
    stub_mastery_evaluation(
        monkeypatch,
        json.dumps(
            {
                "results": [
                    {"questionId": "other", "passed": True, "basis": "不属于本次核验问题。"}
                ]
            },
            ensure_ascii=False,
        ),
    )

    with mastery_service(settings) as (database_session, service):
        session = database_session.get(SessionModel, session_id)
        question = database_session.get(QuestionModel, question_id)
        result = service.evaluate_answers(
            question=question,
            session=session,
            questions=[
                MasteryCheckQuestionInput(
                    question_id="mc1",
                    question="你在合并数量这一步依据的是什么？",
                    evidence_refs=[
                        {
                            "source": "EVALUATION",
                            "sourceId": str(evaluation_id),
                            "quote": "学生写出了计算方向，但没有说明依据。",
                        }
                    ],
                )
            ],
            answers=[MasteryCheckAnswer(question_id="mc1", answer="我把两个数合起来。")],
        )

    assert result is None
    session = read_session(settings, session_id)
    assert session.need_human_reason is not None
    assert "重试次数内仍不合法" in session.need_human_reason
    assert "AI_MASTERY_CHECK_SCHEMA_RETRY_EXHAUSTED" in read_trigger_types(settings, session_id)


def test_valid_answer_assessment_is_recorded(settings, monkeypatch) -> None:
    prepare_client(settings, monkeypatch)
    session_id, question_id, attempt_id, evaluation_id = seed_valid_evaluation(settings)
    stub_mastery_evaluation(monkeypatch, json.dumps(VALID_ASSESSMENT, ensure_ascii=False))

    with mastery_service(settings) as (database_session, service):
        session = database_session.get(SessionModel, session_id)
        question = database_session.get(QuestionModel, question_id)
        result = service.evaluate_answers(
            question=question,
            session=session,
            questions=[
                MasteryCheckQuestionInput(
                    question_id="mc1",
                    question="你在合并数量这一步依据的是什么？",
                    evidence_refs=[
                        {
                            "source": "EVALUATION",
                            "sourceId": str(evaluation_id),
                            "quote": "学生写出了计算方向，但没有说明依据。",
                        }
                    ],
                )
            ],
            answers=[MasteryCheckAnswer(question_id="mc1", answer="我把两个数合起来。")],
        )

    assert result is not None
    assert result.results[0].question_id == "mc1"
    assert result.results[0].passed is False
    calls = read_mastery_calls(settings, session_id)
    assert calls and calls[-1].call_type == "MASTERY_CHECK_ASSESSMENT"
    assert calls[-1].validation_status == "VALID"
