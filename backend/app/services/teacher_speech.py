import hashlib
import io
import json
import threading
import wave
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from app.core.config import Settings
from app.models.tts_voice import TTSVoice

# 应用保护限额，不代表供应商协议上限；超限明确失败，不截断教学内容。
MAX_SPEECH_CHARACTERS = 20000


class TeacherSpeechError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class TeacherSpeechService:
    def __init__(self, settings: Settings, http_client: httpx.Client) -> None:
        self.settings = settings
        self.http_client = http_client
        self.cache_directory = settings.audio_storage_dir / "teacher-tts"
        self._guard = threading.Lock()
        self._locks: dict[str, tuple[threading.Lock, int]] = {}

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
