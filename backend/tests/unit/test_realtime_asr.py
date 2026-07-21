import asyncio

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
