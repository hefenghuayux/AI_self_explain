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


def load_events(settings, session_id: object) -> list[SessionEvent]:
    """按 seq 读取一个会话的全部会话事件。"""
    engine = create_engine(settings.database_url)
    try:
        with OrmSession(engine) as database_session:
            return list(
                database_session.scalars(
                    select(SessionEvent)
                    .where(SessionEvent.session_id == session_id)
                    .order_by(SessionEvent.seq)
                )
            )
    finally:
        engine.dispose()


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

    events = load_events(settings, started["id"])

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


def test_guided_answers_write_user_message_events(settings, monkeypatch) -> None:
    """子问题作答也要写 user.message，否则轨迹里看不到学生答了什么。"""

    def fake_evaluate(self, request: ModelRequestSnapshot) -> AIModelResponse:
        if request.purpose == "AI_SUPPORT":
            content = {
                "action": "GUIDED_QUESTIONS",
                "content": "请先回答下面两个问题。",
                "questions": [
                    {"id": "q1", "question": "第一个 1 表示什么？"},
                    {"id": "q2", "question": "两个 1 合起来是多少？"},
                ],
            }
        else:
            assert request.purpose == "GUIDED_ANSWER_ASSESSMENT"
            content = {
                "results": [
                    {"questionId": item["id"], "result": "CORRECT"}
                    for item in request.blocks.user_input["questions"]
                ],
                "content": "两个条件都确认了，请把它们写进过程。",
            }
        return AIModelResponse('{"choices":[]}', json.dumps(content), 3)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    migrate_database(settings, monkeypatch)
    with authenticated_test_client(settings) as client:
        question = client.post("/api/questions", json=question_payload()).json()
        created = client.post("/api/sessions", json={"questionId": question["id"]}).json()
        session = client.post(
            f"/api/sessions/{created['id']}/initial-choice",
            json={"choice": "NOT_KNOW", "version": created["version"]},
        ).json()
        prompted = client.post(
            f"/api/sessions/{session['id']}/request-support",
            json={"mainDraft": "我知道题目有两个 1。", "version": session["version"]},
        )
        assert prompted.status_code == 200
        partial = client.post(
            f"/api/sessions/{session['id']}/guided-answers",
            json={
                "version": prompted.json()["version"],
                "answers": [{"questionId": "q1", "answer": "一个数量"}],
            },
        )
        assert partial.status_code == 200
        completed = client.post(
            f"/api/sessions/{session['id']}/guided-answers",
            json={
                "version": partial.json()["version"],
                "answers": [{"questionId": "q2", "answer": "等于 2"}],
            },
        )
        assert completed.status_code == 200
        session_id = session["id"]

    events = load_events(settings, session_id)
    messages = [event for event in events if event.event_type == "user.message"]
    assert [event.data["text"] for event in messages] == [
        "我知道题目有两个 1。",
        "第一个 1 表示什么？\n答：一个数量",
        "两个 1 合起来是多少？\n答：等于 2",
    ]
    assert [event.data["inputType"] for event in messages] == ["text", "text", "text"]

    # 学生输入与它触发的模型调用同属一次运行；只答一部分时没有模型调用，自成一次运行。
    requests = [event for event in events if event.event_type == "model.requested"]
    assert len(requests) == 2
    assert messages[0].run_id == requests[0].run_id
    assert messages[2].run_id == requests[1].run_id
    assert messages[1].run_id not in {event.run_id for event in requests}


def test_doubt_and_appeal_write_user_message_events(settings, monkeypatch) -> None:
    """疑问与申诉也要写 user.message：申诉没有模型调用，靠自己一次运行留下学生输入。"""

    def fake_evaluate(self, request: ModelRequestSnapshot) -> AIModelResponse:
        if request.purpose == "AI_EVALUATION":
            content = {
                "correctness": "WRONG",
                "completeness": "INCOMPLETE",
                "hasProgress": True,
                "mainReason": "知识应用问题",
                "otherReasons": [],
                "judgeReason": "学生尚未说明计算依据。",
            }
        elif request.purpose == "AI_TEACHING":
            content = {"content": "请补充合并两个数量的依据。", "questions": []}
        else:
            assert request.purpose == "AI_SUPPORT"
            content = {
                "action": "SIMPLE_DOUBT_ANSWER",
                "content": "两个 1 合起来就是 2。",
                "questions": [],
            }
        return AIModelResponse('{"choices":[]}', json.dumps(content), 3)

    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    migrate_database(settings, monkeypatch)
    with authenticated_test_client(settings) as client:
        started = create_started_session(client)
        attempt = client.post(
            f"/api/sessions/{started['id']}/text-attempts",
            json={"confirmedText": "我把两个 1 合起来。", "version": started["version"]},
        )
        assert attempt.status_code == 200
        doubt = client.post(
            f"/api/sessions/{started['id']}/ask-doubt",
            json={
                "mainDraft": "我把两个 1 合起来。",
                "doubtText": "为什么要合起来？",
                "version": attempt.json()["version"],
            },
        )
        assert doubt.status_code == 200
        appeal = client.post(
            f"/api/sessions/{started['id']}/appeal",
            json={
                "reason": "我认为我的过程没有问题。",
                "version": doubt.json()["version"],
            },
        )
        assert appeal.status_code == 200
        session_id = started["id"]
        appeal_version = doubt.json()["version"]

    events = load_events(settings, session_id)
    messages = [event for event in events if event.event_type == "user.message"]
    assert [event.data["text"] for event in messages] == [
        "我把两个 1 合起来。",
        "为什么要合起来？",
        "我认为我的过程没有问题。",
    ]
    requests = [event for event in events if event.event_type == "model.requested"]
    # 自讲评价与教学反馈、疑问支持共三次模型调用：自讲和疑问各自一次运行。
    assert len(requests) == 3
    assert messages[0].run_id == requests[0].run_id
    assert messages[1].run_id == requests[-1].run_id
    assert messages[1].run_id != messages[0].run_id
    assert messages[2].run_id == f"run_session_{session_id}_appeal_{appeal_version}"
