import asyncio
import sys
import types

from app.services import realtime_asr
from app.services.realtime_asr import ASRStreamEvent, RealtimeASRService


class FakeRecognition:
    def __init__(self) -> None:
        self.started = False
        self.frames: list[bytes] = []
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def send_audio_frame(self, frame: bytes) -> None:
        self.frames.append(frame)

    def stop(self) -> None:
        self.stopped = True


def test_realtime_asr_uses_configured_recognition_and_forwards_audio(settings, monkeypatch) -> None:
    async def run() -> None:
        recognition = FakeRecognition()
        captured: dict[str, object] = {}

        def fake_create_recognition(**kwargs):
            captured.update(kwargs)
            return recognition

        monkeypatch.setattr(realtime_asr, "create_recognition", fake_create_recognition)
        service = RealtimeASRService(settings=settings, loop=asyncio.get_running_loop())

        service.start()
        service.send_audio_frame(b"\x00\x00\x01\x00")
        service.stop()

        assert captured["settings"] is settings
        assert recognition.started is True
        assert recognition.frames == [b"\x00\x00\x01\x00"]
        assert recognition.stopped is True
        assert service.stopped is True

    asyncio.run(run())


def test_realtime_asr_events_can_be_safely_consumed_by_async_route(settings, monkeypatch) -> None:
    async def run() -> None:
        def fake_create_recognition(**kwargs):
            event_queue = kwargs["event_queue"]
            event_queue.put_nowait(ASRStreamEvent(event_type="final_transcript", text="最终转写"))
            return FakeRecognition()

        monkeypatch.setattr(realtime_asr, "create_recognition", fake_create_recognition)
        service = RealtimeASRService(settings=settings, loop=asyncio.get_running_loop())
        service.start()

        event = await service.events.get()
        assert event == ASRStreamEvent(event_type="final_transcript", text="最终转写")

    asyncio.run(run())


def test_realtime_asr_error_callback_preserves_details(settings, monkeypatch) -> None:
    async def run() -> None:
        class FakeRecognitionCallback:
            pass

        class FakeRecognitionResult:
            pass

        class FakeRecognition:
            def __init__(self, **kwargs) -> None:
                self.callback = kwargs["callback"]

        fake_asr_module = types.ModuleType("dashscope.audio.asr")
        fake_asr_module.Recognition = FakeRecognition
        fake_asr_module.RecognitionCallback = FakeRecognitionCallback
        fake_asr_module.RecognitionResult = FakeRecognitionResult
        monkeypatch.setitem(sys.modules, "dashscope.audio.asr", fake_asr_module)

        event_queue: asyncio.Queue[ASRStreamEvent] = asyncio.Queue()
        service = realtime_asr.create_recognition(
            settings=settings,
            event_queue=event_queue,
            loop=asyncio.get_running_loop(),
        )
        service.callback.on_error(
            types.SimpleNamespace(
                message="模型不支持当前业务空间",
                code="InvalidParameter",
                request_id="request-1",
                status_code=400,
            )
        )

        event = await event_queue.get()
        assert event.error_message == "模型不支持当前业务空间"
        assert event.raw_response == {
            "status_code": 400,
            "request_id": "request-1",
            "code": "InvalidParameter",
            "message": "模型不支持当前业务空间",
        }

    asyncio.run(run())


def test_realtime_asr_stop_is_idempotent_after_sdk_stops_recognition(settings, monkeypatch) -> None:
    class AlreadyStoppedRecognition(FakeRecognition):
        _running = False

        def stop(self) -> None:
            raise AssertionError("stop should not be called after SDK stopped recognition")

    async def run() -> None:
        monkeypatch.setattr(
            realtime_asr,
            "create_recognition",
            lambda **kwargs: AlreadyStoppedRecognition(),
        )
        service = RealtimeASRService(settings=settings, loop=asyncio.get_running_loop())
        service.start()
        service.stop()
        assert service.stopped is True

    asyncio.run(run())
