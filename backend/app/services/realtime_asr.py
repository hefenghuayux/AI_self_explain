import asyncio
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings


class ASRServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ASRStreamEvent:
    event_type: str
    text: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    raw_response: dict[str, Any] | None = None


def configure_dashscope(settings: Settings) -> None:
    try:
        import dashscope
    except ImportError as error:
        raise ASRServiceError("缺少 dashscope 依赖，无法启动实时 ASR") from error
    dashscope.api_key = settings.asr_api_key.get_secret_value()
    dashscope.base_websocket_api_url = str(settings.asr_base_url)


def create_recognition(
    *,
    settings: Settings,
    event_queue: asyncio.Queue[ASRStreamEvent],
    loop: asyncio.AbstractEventLoop,
):
    try:
        from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
    except ImportError as error:
        raise ASRServiceError("缺少 dashscope 依赖，无法启动实时 ASR") from error

    class Callback(RecognitionCallback):
        def on_open(self) -> None:
            loop.call_soon_threadsafe(event_queue.put_nowait, ASRStreamEvent(event_type="opened"))

        def on_close(self) -> None:
            loop.call_soon_threadsafe(event_queue.put_nowait, ASRStreamEvent(event_type="closed"))

        def on_complete(self) -> None:
            loop.call_soon_threadsafe(
                event_queue.put_nowait, ASRStreamEvent(event_type="completed")
            )

        def on_error(self, message) -> None:
            error_message = getattr(message, "message", str(message))
            loop.call_soon_threadsafe(
                event_queue.put_nowait,
                ASRStreamEvent(
                    event_type="error",
                    error_type="ASR_SERVICE_ERROR",
                    error_message=error_message,
                ),
            )

        def on_event(self, result: RecognitionResult) -> None:
            sentence = result.get_sentence()
            text = sentence.get("text")
            if not text:
                return
            is_final = RecognitionResult.is_sentence_end(sentence)
            loop.call_soon_threadsafe(
                event_queue.put_nowait,
                ASRStreamEvent(
                    event_type="final_transcript" if is_final else "partial_transcript",
                    text=text,
                    raw_response=sentence,
                ),
            )

    return Recognition(
        model=settings.asr_model,
        format=settings.asr_audio_format,
        sample_rate=settings.asr_sample_rate_hz,
        semantic_punctuation_enabled=settings.asr_semantic_punctuation_enabled,
        callback=Callback(),
    )


class RealtimeASRService:
    def __init__(self, *, settings: Settings, loop: asyncio.AbstractEventLoop) -> None:
        self.settings = settings
        self.events: asyncio.Queue[ASRStreamEvent] = asyncio.Queue()
        self.loop = loop
        self.recognition = None
        self.stopped = False

    def start(self) -> None:
        try:
            self.recognition = create_recognition(
                settings=self.settings, event_queue=self.events, loop=self.loop
            )
            self.recognition.start()
        except ASRServiceError:
            raise
        except Exception as error:
            raise ASRServiceError(f"启动实时 ASR 失败：{error}") from error

    def send_audio_frame(self, frame: bytes) -> None:
        if self.recognition is None:
            raise ASRServiceError("实时 ASR 尚未启动")
        try:
            self.recognition.send_audio_frame(frame)
        except Exception as error:
            raise ASRServiceError(f"发送实时音频帧失败：{error}") from error

    def stop(self) -> None:
        if self.recognition is None or self.stopped:
            return
        try:
            self.recognition.stop()
        except Exception as error:
            raise ASRServiceError(f"停止实时 ASR 失败：{error}") from error
        self.stopped = True
