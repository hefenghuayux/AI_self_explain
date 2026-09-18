import json
from pathlib import Path

from alembic.config import Config
from conftest import authenticated_test_client
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from alembic import command
from app.models.session_event import SessionEvent
from app.schemas.model_request_snapshot import ModelRequestSnapshot
from app.services.ai_evaluation import AIModelClient, AIModelResponse


def question_payload() -> dict[str, object]:
    return {
        "questionContent": "计算 1 + 1。",
        "standardAnswer": "2",
        "rubricPoints": ["正确计算加法", "得出结果 2"],
        "commonErrors": ["把结果写成 3"],
        "alternativeSolutions": ["使用实物计数"],
        "layeredHints": ["先数一数两个数"],
        "guidedQuestions": ["两个 1 合起来是多少？"],
        "fullSolution": "1 加 1 等于 2。",
    }


def migrate_database(settings, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")


def create_started_session(client: TestClient) -> dict[str, object]:
    question = client.post("/api/questions", json=question_payload()).json()
    session = client.post("/api/sessions", json={"questionId": question["id"]}).json()
    choice = client.post(
        f"/api/sessions/{session['id']}/initial-choice",
        json={"choice": "KNOW", "version": session["version"]},
    )
    assert choice.status_code == 200
    return choice.json()


def test_text_self_explanation_writes_real_event_chain(settings, monkeypatch) -> None:
    evaluation_content = json.dumps(
        {
            "correctness": "CORRECT",
            "completeness": "COMPLETE",
            "hasProgress": True,
            "mainReason": None,
            "otherReasons": [],
            "judgeReason": None,
        }
    )

    def fake_evaluate(self, request: ModelRequestSnapshot) -> AIModelResponse:
        assert request.purpose == "AI_EVALUATION"
        return AIModelResponse('{"choices":[]}', evaluation_content, 3)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    migrate_database(settings, monkeypatch)
    with authenticated_test_client(settings) as client:
        started = create_started_session(client)
        response = client.post(
            f"/api/sessions/{started['id']}/text-attempts",
            json={"confirmedText": "1 加 1 等于 2。", "version": started["version"]},
        )
        assert response.status_code == 200

    engine = create_engine(settings.database_url)
    try:
        with OrmSession(engine) as database_session:
            events = list(
                database_session.scalars(
                    select(SessionEvent)
                    .where(SessionEvent.session_id == started["id"])
                    .order_by(SessionEvent.seq)
                )
            )
    finally:
        engine.dispose()

    # 只断言必要事件存在：审计字段增加不应让事件链断言失效。
    event_types = [event.event_type for event in events]
    for required in (
        "session.started",
        "user.message",
        "context.added",
        "model.requested",
        "model.responded",
        "state.changed",
    ):
        assert required in event_types

    # seq 是统一的时间顺序来源：唯一且单调递增。
    seqs = [event.seq for event in events]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))

    requests = [event for event in events if event.event_type == "model.requested"]
    responses = [event for event in events if event.event_type == "model.responded"]
    assert len(requests) == 1
    assert len(responses) == 1
    requested, responded = requests[0], responses[0]
    assert responded.parent_event_id == requested.event_id
    assert responded.seq > requested.seq

    # 事件链按父子关系串起来，而不是按固定下标。
    user_message = next(event for event in events if event.event_type == "user.message")
    contexts = [event for event in events if event.event_type == "context.added"]
    submit_transition = next(
        event
        for event in events
        if event.event_type == "state.changed" and event.parent_event_id == user_message.event_id
    )
    assert submit_transition.seq > user_message.seq
    assert all(event.parent_event_id == submit_transition.event_id for event in contexts)
    assert requested.parent_event_id == contexts[-1].event_id
    final_state = [event for event in events if event.event_type == "state.changed"][-1]
    assert final_state.parent_event_id == responded.event_id

    # 同一轮自讲的所有事件共享一个 run_id。
    run_events = [event for event in events if event.run_id is not None]
    assert {event.run_id for event in run_events} == {user_message.run_id}

    # 请求快照仍保留分层消息，末层携带本轮学生文本。
    messages = requested.data["messages"]
    assert messages[0]["role"] == "system"
    assert all(message["content"] for message in messages)
    # 题目材料里可能出现同样的字符串，因此只校验末层本轮任务数据。
    assert messages[-1]["role"] == "user"
    assert "1 加 1 等于 2。" in messages[-1]["content"]

    assert responded.data["rawContent"] == evaluation_content
    assert responded.data["validation"] == "valid"
