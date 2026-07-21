import asyncio
import json
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DatabaseSession

from alembic import command
from app.main import create_app
from app.models.audio_file import AudioFile
from app.models.explanation_attempt import ExplanationAttempt
from app.models.external_call_record import ExternalCallRecord
from app.models.session import Session
from app.repositories.sessions import SessionRepository
from app.services import realtime_asr
from app.services.ai_evaluation import AIModelClient, AIModelResponse
from app.services.audio_storage import AudioStorage, AudioStorageError
from app.services.realtime_asr import ASRStreamEvent


def migrate_database(settings, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    alembic_config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.upgrade(alembic_config, "head")


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


def test_realtime_voice_transcript_is_confirmed_before_ai_evaluation(settings, monkeypatch) -> None:
    class FakeRecognition:
        def __init__(self, event_queue: asyncio.Queue[ASRStreamEvent]) -> None:
            self.event_queue = event_queue
            self.sent = False

        def start(self) -> None:
            return None

        def send_audio_frame(self, frame: bytes) -> None:
            if self.sent:
                return
            self.sent = True
            self.event_queue.put_nowait(
                ASRStreamEvent(event_type="partial_transcript", text="1 加 1 等")
            )
            self.event_queue.put_nowait(
                ASRStreamEvent(
                    event_type="final_transcript",
                    text="1 加 1 等于 2。",
                    raw_response={"text": "1 加 1 等于 2。", "end_time": 1},
                )
            )

        def stop(self) -> None:
            self.event_queue.put_nowait(ASRStreamEvent(event_type="completed"))

    def fake_create_recognition(**kwargs):
        return FakeRecognition(kwargs["event_queue"])

    def fake_evaluate(self, prompt: str, schema: dict[str, object]) -> AIModelResponse:
        assert '"confirmedText": "学生修改后的最终文本"' in prompt
        return AIModelResponse(
            raw_response='{"choices": []}',
            content=(
                '{"correctness":"CORRECT","completeness":"INCOMPLETE",'
                '"coveredPoints":["正确计算加法"],"missingPoints":["得出结果 2"],'
                '"errorEvidence":[],"feedback":"请补充结果。","confidence":1,'
                '"nextAction":"ASK_FOCUSED_QUESTION","needHumanReason":null}'
            ),
            duration_ms=1,
        )

    monkeypatch.setattr(realtime_asr, "create_recognition", fake_create_recognition)
    monkeypatch.setattr(AIModelClient, "evaluate", fake_evaluate)
    migrate_database(settings, monkeypatch)

    with TestClient(create_app(settings)) as client:
        question = client.post("/api/questions", json=question_payload()).json()
        session = client.post("/api/sessions", json={"questionId": question["id"]}).json()
        session = client.post(
            f"/api/sessions/{session['id']}/initial-choice",
            json={"choice": "KNOW", "version": session["version"]},
        ).json()

        with client.websocket_connect(
            f"/api/sessions/{session['id']}/voice-stream?version={session['version']}"
        ) as websocket:
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_bytes(b"\x00\x00" * 1600)
            assert websocket.receive_json() == {"type": "partial_transcript", "text": "1 加 1 等"}
            assert websocket.receive_json() == {
                "type": "final_transcript",
                "text": "1 加 1 等于 2。",
            }
            websocket.send_text(json.dumps({"type": "stop"}))
            completed = websocket.receive_json()

        assert completed["type"] == "completed"
        pending = client.get(f"/api/sessions/{session['id']}").json()
        assert pending["flowStage"] == "CONFIRMING_TEXT"
        assert pending["pendingVoiceAttempt"]["asrTranscript"] == "1 加 1 等于 2。"

        confirmed = client.post(
            f"/api/sessions/{session['id']}/voice-attempts/confirm",
            json={
                "attemptId": completed["attemptId"],
                "confirmedText": "学生修改后的最终文本",
                "version": completed["version"],
            },
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["flowStage"] == "WAIT_STUDENT_ACTION"

    engine = create_engine(settings.database_url)
    try:
        with DatabaseSession(engine) as database_session:
            audio_file = database_session.scalars(select(AudioFile)).one()
            attempt = database_session.scalars(select(ExplanationAttempt)).one()
            asr_call = database_session.scalars(
                select(ExternalCallRecord).where(ExternalCallRecord.call_type == "ASR")
            ).one()
        assert audio_file.size_bytes == 3200
        assert Path(settings.audio_storage_dir, audio_file.relative_path).is_file()
        assert attempt.input_mode == "VOICE"
        assert attempt.asr_transcript == "1 加 1 等于 2。"
        assert attempt.confirmed_text == "学生修改后的最终文本"
        assert asr_call.call_type == "ASR"
        assert asr_call.status == "SUCCESS"
    finally:
        engine.dispose()


def test_audio_write_failure_does_not_create_partial_database_records(
    settings, monkeypatch
) -> None:
    migrate_database(settings, monkeypatch)
    with TestClient(create_app(settings)) as client:
        question = client.post("/api/questions", json=question_payload()).json()
        created_session = client.post("/api/sessions", json={"questionId": question["id"]}).json()
        client.post(
            f"/api/sessions/{created_session['id']}/initial-choice",
            json={"choice": "KNOW", "version": created_session["version"]},
        )

    engine = create_engine(settings.database_url)
    try:
        with DatabaseSession(engine) as database_session:
            session = database_session.get(Session, created_session["id"])
            assert session is not None
            repository = SessionRepository(database_session)
            storage = AudioStorage(settings)
            capture = storage.start_capture(session.id)
            capture.append(b"\x00\x00")

            def fail_finalize(*args, **kwargs):
                raise AudioStorageError("测试写入失败")

            monkeypatch.setattr(storage, "finalize_capture", fail_finalize)
            with pytest.raises(AudioStorageError, match="测试写入失败"):
                repository.complete_voice_transcription(
                    session=session,
                    capture=capture,
                    audio_storage=storage,
                    asr_transcript="测试转写",
                )

        with DatabaseSession(engine) as database_session:
            assert database_session.scalars(select(AudioFile)).all() == []
            assert database_session.scalars(select(ExplanationAttempt)).all() == []
    finally:
        engine.dispose()
