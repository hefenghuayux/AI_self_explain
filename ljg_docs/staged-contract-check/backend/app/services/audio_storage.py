import hashlib
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings


class AudioStorageError(RuntimeError):
    pass


class AudioCapture:
    def __init__(self, *, temporary_path: Path, max_size_bytes: int) -> None:
        self.temporary_path = temporary_path
        self.max_size_bytes = max_size_bytes
        self.size_bytes = 0
        self.sha256 = hashlib.sha256()
        try:
            self._file = temporary_path.open("xb")
        except OSError as error:
            raise AudioStorageError(f"无法创建音频临时文件：{temporary_path}") from error

    def append(self, frame: bytes) -> None:
        if not frame:
            raise AudioStorageError("音频帧不能为空")
        if len(frame) % 2 != 0:
            raise AudioStorageError("PCM 音频帧必须使用 16 位采样")
        if self.size_bytes + len(frame) > self.max_size_bytes:
            raise AudioStorageError("音频超过配置的大小或时长限制")
        try:
            self._file.write(frame)
            self._file.flush()
        except OSError as error:
            raise AudioStorageError(f"写入音频临时文件失败：{self.temporary_path}") from error
        self.size_bytes += len(frame)
        self.sha256.update(frame)

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def read_frames(self, frame_size: int):
        if frame_size <= 0:
            raise AudioStorageError("音频帧大小必须大于 0")
        try:
            self._file.flush()
            with self.temporary_path.open("rb") as saved_audio:
                while frame := saved_audio.read(frame_size):
                    yield frame
        except OSError as error:
            raise AudioStorageError(f"读取音频临时文件失败：{self.temporary_path}") from error

    def delete(self) -> None:
        self.close()
        self.temporary_path.unlink(missing_ok=True)


class AudioStorage:
    def __init__(self, settings: Settings) -> None:
        self.root_directory = settings.audio_storage_dir
        duration_size_bytes = (
            settings.audio_max_duration_seconds
            * settings.asr_sample_rate_hz
            * settings.asr_channels
            * 2
        )
        self.max_size_bytes = min(settings.audio_max_size_mib * 1024 * 1024, duration_size_bytes)
        self.content_type = (
            f"audio/L16;rate={settings.asr_sample_rate_hz};channels={settings.asr_channels}"
        )

    def start_capture(self, session_id: int) -> AudioCapture:
        session_directory = self.root_directory / str(session_id)
        try:
            session_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise AudioStorageError(f"无法创建会话音频目录：{session_directory}") from error
        return AudioCapture(
            temporary_path=session_directory / f".{uuid4().hex}.pcm.part",
            max_size_bytes=self.max_size_bytes,
        )

    def finalize_capture(
        self, capture: AudioCapture, *, session_id: int, audio_file_id: int
    ) -> str:
        if capture.size_bytes == 0:
            raise AudioStorageError("不能保存空音频")
        capture.close()
        relative_path = Path(str(session_id)) / f"{audio_file_id}.pcm"
        final_path = self.root_directory / relative_path
        try:
            capture.temporary_path.replace(final_path)
        except OSError as error:
            raise AudioStorageError(f"保存音频文件失败：{final_path}") from error
        return relative_path.as_posix()

    def delete_relative_path(self, relative_path: str) -> None:
        (self.root_directory / relative_path).unlink(missing_ok=True)
