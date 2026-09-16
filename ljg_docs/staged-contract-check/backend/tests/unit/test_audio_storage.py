import hashlib

import pytest

from app.services.audio_storage import AudioCapture, AudioStorage, AudioStorageError


def test_pcm_capture_is_saved_with_configured_session_relative_path(settings) -> None:
    storage = AudioStorage(settings)
    capture = storage.start_capture(session_id=12)
    capture.append(b"\x00\x00\x01\x00")

    relative_path = storage.finalize_capture(capture, session_id=12, audio_file_id=8)

    saved_file = settings.audio_storage_dir / relative_path
    assert relative_path == "12/8.pcm"
    assert saved_file.read_bytes() == b"\x00\x00\x01\x00"
    assert capture.size_bytes == 4
    assert capture.sha256.hexdigest() == hashlib.sha256(b"\x00\x00\x01\x00").hexdigest()


def test_pcm_capture_rejects_over_limit_or_invalid_sample_size(tmp_path) -> None:
    capture = AudioCapture(temporary_path=tmp_path / "audio.pcm.part", max_size_bytes=4)
    capture.append(b"\x00\x00\x01\x00")

    with pytest.raises(AudioStorageError, match="大小或时长"):
        capture.append(b"\x02\x00")
    with pytest.raises(AudioStorageError, match="16 位"):
        capture.append(b"\x00")
    capture.delete()
