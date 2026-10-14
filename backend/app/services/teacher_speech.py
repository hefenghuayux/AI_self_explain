import base64
import binascii
import hashlib
import io
import json
import logging
import threading
import time
import wave
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from app.core.config import Settings
from app.models.tts_voice import TTSVoice

# 应用保护限额，不代表供应商协议上限；超限明确失败，不截断教学内容。
MAX_SPEECH_CHARACTERS = 20000
MAX_STREAM_BYTES = 32 * 1024 * 1024
MAX_PENDING_STREAMS = 16
logger = logging.getLogger(__name__)


class TeacherSpeechError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass
class SpeechStream:
    condition: threading.Condition = field(default_factory=threading.Condition)
    chunks: list[bytes] = field(default_factory=list)
    finished: bool = False
    error: TeacherSpeechError | None = None


class TeacherSpeechService:
    def __init__(self, settings: Settings, http_client: httpx.Client) -> None:
        self.settings = settings
        self.http_client = http_client
        self.cache_directory = settings.audio_storage_dir / "teacher-tts"
        self._guard = threading.Lock()
        self._locks: dict[str, tuple[threading.Lock, int]] = {}
        self._streams: dict[str, SpeechStream] = {}
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="teacher-tts")
        self._closed = False

    def close(self) -> None:
        # 已开始的合成在退出前完成；HTTP client 必须在这些任务之后关闭。
        with self._guard:
            self._closed = True
        self._executor.shutdown(wait=True)

    def _stream_body(self, text: str, voice: TTSVoice) -> dict:
        settings = self.settings
        if not (
            settings.tts_provider.strip()
            and settings.tts_base_url
            and settings.tts_api_key.get_secret_value().strip()
        ):
            raise TeacherSpeechError("TTS_NOT_CONFIGURED", "教师语音尚未配置", 503)
        if not text.strip():
            raise TeacherSpeechError("TTS_EMPTY_TEXT", "没有可朗读的文本", 422)
        if len(text) > MAX_SPEECH_CHARACTERS:
            raise TeacherSpeechError("TTS_TEXT_TOO_LONG", "朗读文本超过 20000 字符限额", 422)
        return {
            "model": settings.tts_model.strip() or voice.model,
            "input": {
                "text": text,
                "voice": voice.voice_id,
                "instruction": voice.instruction,
                "format": "pcm",
                "sample_rate": 24000,
            },
        }

    def _start_stream(self, body: dict) -> tuple[Path, SpeechStream | None]:
        key = hashlib.sha256(
            json.dumps({"version": 1, **body}, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        path = self.cache_directory / f"{key}.pcm"
        with self._guard:
            if path.is_file():
                logger.info("教师语音命中缓存", extra={"eventName": "tts.cache.hit"})
                return path, None
            if key in self._streams:
                return path, self._streams[key]
            if self._closed:
                raise TeacherSpeechError("TTS_UNAVAILABLE", "教师语音服务正在关闭", 503)
            if len(self._streams) >= MAX_PENDING_STREAMS:
                raise TeacherSpeechError("TTS_BUSY", "教师语音生成繁忙，请稍后重试", 503)
            stream = SpeechStream()
            self._streams[key] = stream
            try:
                self._executor.submit(self._produce_stream, key, body, path, stream)
            except RuntimeError as error:
                del self._streams[key]
                raise TeacherSpeechError("TTS_UNAVAILABLE", "无法启动教师语音生成", 503) from error
            return path, stream

    def prewarm(self, text: str, voice: TTSVoice) -> None:
        # 在线程边界前把 ORM 音色转换成普通请求快照，不共享数据库会话。
        self._start_stream(self._stream_body(text, voice))

    def stream(self, text: str, voice: TTSVoice) -> Iterator[bytes]:
        path, stream = self._start_stream(self._stream_body(text, voice))
        return self._read_stream(path, stream)

    @staticmethod
    def _read_stream(path: Path, stream: SpeechStream | None) -> Iterator[bytes]:
        if stream is None:
            with path.open("rb") as source:
                while chunk := source.read(19200):
                    yield chunk
            return
        index = 0
        while True:
            with stream.condition:
                stream.condition.wait_for(
                    lambda index=index: index < len(stream.chunks) or stream.finished
                )
                if stream.error is not None:
                    raise stream.error
                if index < len(stream.chunks):
                    chunk = stream.chunks[index]
                    index += 1
                else:
                    return
            # 每个消费者从第 0 块开始补读；离开消费者不取消生产者。
            yield chunk

    def _produce_stream(self, key: str, body: dict, path: Path, stream: SpeechStream) -> None:
        started_at = time.perf_counter()
        temporary_path = self.cache_directory / f".{key}.{uuid4().hex}.part"
        size = 0
        try:
            self.cache_directory.mkdir(parents=True, exist_ok=True)
            with temporary_path.open("wb") as destination:
                for chunk in self._generate_stream(body):
                    size += len(chunk)
                    if size > MAX_STREAM_BYTES:
                        raise TeacherSpeechError("TTS_AUDIO_TOO_LARGE", "教师语音超过 32 MiB 限额")
                    destination.write(chunk)
                    with stream.condition:
                        stream.chunks.append(chunk)
                        stream.condition.notify_all()
                    if len(stream.chunks) == 1:
                        logger.info(
                            "教师语音首块返回",
                            extra={
                                "eventName": "tts.first_audio",
                                "durationMs": round((time.perf_counter() - started_at) * 1000),
                            },
                        )
            if not size or size % 2:
                raise TeacherSpeechError("TTS_INVALID_AUDIO", "教师语音 PCM 为空或采样不完整")
            # 只在供应商明确成功结束后发布完整缓存，半成品始终不可命中。
            temporary_path.replace(path)
            logger.info(
                "教师语音生成完成",
                extra={
                    "eventName": "tts.completed",
                    "durationMs": round((time.perf_counter() - started_at) * 1000),
                    "audioBytes": size,
                },
            )
        except TeacherSpeechError as error:
            stream.error = error
        except OSError:
            stream.error = TeacherSpeechError("TTS_CACHE_FAILED", "保存教师语音缓存失败", 503)
        except Exception:
            # 明确终止并唤醒消费者，不让后台异常留下永远等待的生成任务。
            stream.error = TeacherSpeechError("TTS_STREAM_FAILED", "教师语音流处理失败")
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.error("教师语音临时缓存清理失败")
            if stream.error is not None:
                logger.warning(
                    "教师语音生成失败",
                    extra={
                        "eventName": "tts.failed",
                        "errorType": stream.error.code,
                        "durationMs": round((time.perf_counter() - started_at) * 1000),
                    },
                )
            with stream.condition:
                stream.finished = True
                stream.condition.notify_all()
            with self._guard:
                self._streams.pop(key, None)

    def _generate_stream(self, body: dict) -> Iterator[bytes]:
        started_at = time.perf_counter()
        try:
            with self.http_client.stream(
                "POST",
                str(self.settings.tts_base_url),
                headers={
                    "Authorization": f"Bearer {self.settings.tts_api_key.get_secret_value()}",
                    "X-DashScope-SSE": "enable",
                },
                json=body,
            ) as response:
                response.raise_for_status()
                if (
                    not response.headers.get("content-type", "")
                    .lower()
                    .startswith("text/event-stream")
                ):
                    raise TeacherSpeechError("TTS_NOT_STREAMING", "语音服务未返回 SSE 音频流")
                data_lines: list[str] = []
                for line in response.iter_lines():
                    if time.perf_counter() - started_at > self.settings.tts_request_timeout_seconds:
                        raise TeacherSpeechError("TTS_TIMEOUT", "教师语音生成超时，请重试", 503)
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                    elif not line and data_lines:
                        event = json.loads("\n".join(data_lines))
                        data_lines = []
                        if event.get("code"):
                            raise TeacherSpeechError("TTS_UPSTREAM_ERROR", "语音服务报告合成失败")
                        output = event["output"]
                        audio = output.get("audio") or {}
                        encoded = audio.get("data")
                        # 最后带完整音频 URL 的事件不能再次追加整段音频。
                        if encoded and not audio.get("url"):
                            yield base64.b64decode(encoded, validate=True)
                        if output.get("finish_reason") == "stop":
                            return
                raise TeacherSpeechError("TTS_INCOMPLETE_STREAM", "教师语音流提前中断，请重试")
        except httpx.TimeoutException as error:
            raise TeacherSpeechError("TTS_TIMEOUT", "教师语音生成超时，请重试", 503) from error
        except httpx.HTTPStatusError as error:
            raise TeacherSpeechError(
                "TTS_UPSTREAM_ERROR", f"语音服务请求失败（HTTP {error.response.status_code}）"
            ) from error
        except httpx.RequestError as error:
            raise TeacherSpeechError(
                "TTS_CONNECTION_FAILED", "无法连接语音服务，请重试", 503
            ) from error
        except (KeyError, TypeError, ValueError, binascii.Error) as error:
            raise TeacherSpeechError("TTS_INVALID_RESPONSE", "语音服务返回了无效音频流") from error

    @contextmanager
    def _cache_lock(self, key: str):
        with self._guard:
            lock, users = self._locks.get(key, (threading.Lock(), 0))
            self._locks[key] = (lock, users + 1)
        try:
            with lock:
                yield
        finally:
            with self._guard:
                lock, users = self._locks[key]
                if users == 1:
                    del self._locks[key]
                else:
                    self._locks[key] = (lock, users - 1)

    def synthesize(self, text: str, voice: TTSVoice) -> Path:
        settings = self.settings
        if not (
            settings.tts_provider.strip()
            and settings.tts_base_url
            and settings.tts_api_key.get_secret_value().strip()
        ):
            raise TeacherSpeechError("TTS_NOT_CONFIGURED", "教师语音尚未配置", 503)
        if not text.strip():
            raise TeacherSpeechError("TTS_EMPTY_TEXT", "没有可朗读的文本", 422)
        if len(text) > MAX_SPEECH_CHARACTERS:
            raise TeacherSpeechError(
                "TTS_TEXT_TOO_LONG", "朗读文本超过应用的 20000 字符限额，请分段后重试", 422
            )
        body = {
            "model": settings.tts_model.strip() or voice.model,
            "input": {
                "text": text,
                "voice": voice.voice_id,
                "format": "wav",
                "sample_rate": 24000,
                "instruction": voice.instruction,
            },
        }
        key = hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        path = self.cache_directory / f"{key}.wav"
        with self._cache_lock(key):
            if path.is_file():
                return path
            audio = self._generate(body)
            temporary_path = self.cache_directory / f".{key}.{uuid4().hex}.part"
            try:
                self.cache_directory.mkdir(parents=True, exist_ok=True)
                temporary_path.write_bytes(audio)
                temporary_path.replace(path)
            except OSError as error:
                raise TeacherSpeechError("TTS_CACHE_FAILED", "保存教师语音缓存失败", 503) from error
            finally:
                temporary_path.unlink(missing_ok=True)
        return path

    def _generate(self, body: dict) -> bytes:
        try:
            response = self.http_client.post(
                str(self.settings.tts_base_url),
                headers={"Authorization": f"Bearer {self.settings.tts_api_key.get_secret_value()}"},
                json=body,
            )
            response.raise_for_status()
            audio_url = response.json()["output"]["audio"]["url"]
            if not isinstance(audio_url, str) or urlsplit(audio_url).scheme not in {
                "http",
                "https",
            }:
                raise ValueError("无效音频 URL")
            # 音频下载不携带合成服务的密钥。
            audio_response = self.http_client.get(audio_url)
            audio_response.raise_for_status()
        except httpx.TimeoutException as error:
            raise TeacherSpeechError("TTS_TIMEOUT", "教师语音生成超时，请重试", 503) from error
        except httpx.HTTPStatusError as error:
            raise TeacherSpeechError(
                "TTS_UPSTREAM_ERROR", f"语音服务请求失败（HTTP {error.response.status_code}）"
            ) from error
        except httpx.RequestError as error:
            raise TeacherSpeechError(
                "TTS_CONNECTION_FAILED", "无法连接语音服务，请重试", 503
            ) from error
        except (KeyError, TypeError, ValueError) as error:
            raise TeacherSpeechError(
                "TTS_INVALID_RESPONSE", "语音服务未返回有效音频地址"
            ) from error
        try:
            with wave.open(io.BytesIO(audio_response.content), "rb") as source:
                channels, width, rate = (
                    source.getnchannels(),
                    source.getsampwidth(),
                    source.getframerate(),
                )
                frames = source.readframes(source.getnframes())
            if channels != 1 or width != 2 or rate != 24000 or not frames or len(frames) % 2:
                raise ValueError("无效 WAV 参数或音频为空")
            # 上游 WAV 可能使用流式占位长度，以实际 PCM 帧重新写入正确长度。
            result = io.BytesIO()
            with wave.open(result, "wb") as destination:
                destination.setnchannels(channels)
                destination.setsampwidth(width)
                destination.setframerate(rate)
                destination.writeframes(frames)
            return result.getvalue()
        except (wave.Error, EOFError, ValueError) as error:
            raise TeacherSpeechError("TTS_INVALID_AUDIO", "语音服务返回的 WAV 音频无效") from error
