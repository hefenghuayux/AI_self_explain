"""Durable AI preview snapshots and structural incremental JSON text parsing."""

import asyncio
import json
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field

from sqlalchemy import select

from app.models.ai_run import AIRun


@dataclass(frozen=True)
class StreamContext:
    registry: "AIStreamRegistry"
    run_id: str
    session_id: int


current_stream: ContextVar[StreamContext | None] = ContextVar("current_ai_stream", default=None)


def terminal_snapshot(snapshot: dict, *, result=None, error=None, cancelled=False) -> dict:
    snapshot = deepcopy(snapshot)
    snapshot["status"] = "CANCELLED" if cancelled else "FAILED" if error else "SUCCEEDED"
    snapshot["error"] = error
    if cancelled:
        snapshot["result"] = None
    elif result is not None:
        snapshot["result"] = result
    for channel in snapshot["channels"].values():
        if cancelled or channel["status"] == "GENERATING":
            channel["status"] = "FAILED"
            channel["fields"] = {}
    snapshot["revision"] += 1
    return snapshot


@asynccontextmanager
async def tracked_stream_call(handle):
    """Register the reader with the existing run's cancellation task set."""
    from app.services.ai_run import AIRunCancelled

    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    with handle._lock:
        handle.check()
        handle._tasks.add((loop, task))
    try:
        yield
    except asyncio.CancelledError as error:
        raise AIRunCancelled("AI 运行已取消") from error
    finally:
        with handle._lock:
            handle._tasks.discard((loop, task))


class AIStreamRegistry:
    def __init__(self, database_session_factory) -> None:
        self.database_session_factory = database_session_factory
        self._lock = threading.RLock()
        self._snapshots: OrderedDict[str, dict] = OrderedDict()
        self._persisted_at: dict[str, float] = {}

    def create(self, run_id: str, session_id: int) -> None:
        with self._lock:
            self._snapshots[run_id] = {
                "runId": run_id,
                "status": "RUNNING",
                "revision": 0,
                "channels": {},
                "error": None,
                "result": None,
            }
            self.flush(run_id)

    def snapshot(self, run_id: str) -> dict | None:
        with self._lock:
            if run_id in self._snapshots:
                return deepcopy(self._snapshots[run_id])
            with self.database_session_factory() as db:
                record = db.get(AIRun, run_id)
                return None if record is None else deepcopy(record.checkpoints.get("stream"))

    def begin_channel(self, run_id: str, purpose: str) -> int:
        with self._lock:
            snapshot = self._snapshots[run_id]
            previous = snapshot["channels"].get(purpose, {})
            generation = previous.get("generation", 0) + 1
            if snapshot["status"] == "RUNNING":
                snapshot["channels"][purpose] = {
                    "generation": generation,
                    "status": "GENERATING",
                    "fields": {},
                }
                self._changed(run_id, force=True)
            return generation

    def update_fields(self, run_id: str, purpose: str, generation: int, fields: dict) -> None:
        with self._lock:
            snapshot = self._snapshots[run_id]
            channel = snapshot["channels"].get(purpose)
            if (
                snapshot["status"] != "RUNNING"
                or channel is None
                or channel["generation"] != generation
                or channel["status"] != "GENERATING"
            ):
                return
            if channel["fields"] != fields:
                channel["fields"] = dict(fields)
                self._changed(run_id)

    def validate_channel(self, run_id: str, purpose: str) -> None:
        self._channel_status(run_id, purpose, "VALIDATED")

    def fail_channel(self, run_id: str, purpose: str) -> None:
        self._channel_status(run_id, purpose, "FAILED")

    def _channel_status(self, run_id: str, purpose: str, status: str) -> None:
        with self._lock:
            snapshot = self._snapshots[run_id]
            channel = snapshot["channels"].get(purpose)
            if snapshot["status"] != "RUNNING" or channel is None:
                return
            channel["status"] = status
            if status == "FAILED":
                channel["fields"] = {}
            self._changed(run_id, force=True)

    def update_result(self, run_id: str, result) -> None:
        with self._lock:
            snapshot = self._snapshots[run_id]
            if snapshot["status"] == "RUNNING":
                snapshot["result"] = result
                self._changed(run_id, force=True)

    def finish(self, run_id: str, result=None, error=None, cancelled: bool = False) -> None:
        with self._lock:
            snapshot = self._snapshots.get(run_id)
            if snapshot is None:
                snapshot = self.snapshot(run_id)
                if snapshot is None:
                    return
                self._snapshots[run_id] = snapshot
            if snapshot["status"] != "RUNNING":
                return
            self._snapshots[run_id] = terminal_snapshot(
                snapshot, result=result, error=error, cancelled=cancelled
            )
            self.flush(run_id)
            completed = [
                key for key, value in self._snapshots.items() if value["status"] != "RUNNING"
            ]
            for key in completed[:-128]:
                self._snapshots.pop(key)
                self._persisted_at.pop(key, None)

    def _changed(self, run_id: str, *, force: bool = False) -> None:
        self._snapshots[run_id]["revision"] += 1
        if force or time.monotonic() - self._persisted_at.get(run_id, 0) >= 0.25:
            self.flush(run_id)

    def flush(self, run_id: str) -> None:
        with self._lock:
            with self.database_session_factory() as db:
                record = db.scalar(select(AIRun).where(AIRun.id == run_id).with_for_update())
                if record is None:
                    raise RuntimeError("AI 流运行记录不存在")
                snapshot = self._snapshots[run_id]
                if record.status == "CANCELLED":
                    snapshot["status"] = "CANCELLED"
                    snapshot["result"] = None
                    for channel in snapshot["channels"].values():
                        channel["status"] = "FAILED"
                        channel["fields"] = {}
                record.checkpoints = {**record.checkpoints, "stream": deepcopy(snapshot)}
                db.commit()
            self._persisted_at[run_id] = time.monotonic()


def stream_validated(purpose: str) -> None:
    context = current_stream.get()
    if context is not None:
        context.registry.validate_channel(context.run_id, purpose)


def stream_failed(purpose: str) -> None:
    context = current_stream.get()
    if context is not None:
        context.registry.fail_channel(context.run_id, purpose)


def visible_path(purpose: str, path: tuple) -> bool:
    if purpose in {"AI_TEACHING", "AI_SUPPORT"}:
        return path == ("content",) or (
            len(path) == 3
            and path[0] == "questions"
            and isinstance(path[1], int)
            and path[2] == "question"
        )
    if purpose == "GUIDED_ANSWER_ASSESSMENT":
        return path == ("content",)
    if purpose == "AI_MASTERY_CHECK":
        return (
            len(path) == 3
            and path[0] == "questions"
            and isinstance(path[1], int)
            and path[2] == "question"
        )
    if purpose == "MASTERY_CHECK_ASSESSMENT":
        return (
            len(path) == 3
            and path[0] == "results"
            and isinstance(path[1], int)
            and path[2] == "basis"
        )
    if purpose == "FIRST_EXPLANATION_GRADING":
        return (
            path in {("correctnessReason",), ("completenessReason",), ("summary",)}
            or len(path) == 2
            and path[0] in {"missingRequirements", "rubricLimitations"}
            and isinstance(path[1], int)
            or len(path) == 3
            and path[0] == "ambiguityNotes"
            and isinstance(path[1], int)
            and path[2] in {"source", "interpretation", "impact"}
        )
    return False


@dataclass
class _Frame:
    kind: str
    path: tuple
    state: str
    key: str | None = None
    index: int = 0
    keys: set = field(default_factory=set)


class JSONTextStream:
    """Parse the actual JSON tree incrementally, never matching field names in text."""

    def __init__(
        self, purpose: str, publish, *, support_count: int = 0, support_limit: int = 0
    ) -> None:
        self.purpose = purpose
        self.publish = publish
        self.support_count = support_count
        self.support_limit = support_limit
        self.frames: list[_Frame] = []
        self.root_done = False
        self.token: str | None = None
        self.token_path: tuple = ()
        self.key_token = False
        self.value = ""
        self.escape = False
        self.unicode_digits: str | None = None
        self.high_surrogate: int | None = None
        self.fields: dict[str, str] = {}
        self.action: str | None = None

    def feed(self, text: str) -> None:
        for char in text:
            self._char(char)
        allowed = self.purpose != "AI_SUPPORT" or (
            self.action == "REFUSE_FULL_SOLUTION"
            or self.action in {"GUIDED_QUESTIONS", "SIMPLE_DOUBT_ANSWER"}
            and self.support_count < self.support_limit
        )
        if allowed:
            self.publish(dict(self.fields))

    def finish(self) -> None:
        if self.token == "primitive":
            self._finish_primitive()
        if self.token is not None or self.frames or not self.root_done:
            raise ValueError("AI 流包含未完成的 JSON")

    def _path(self) -> tuple:
        if not self.frames:
            return ()
        parent = self.frames[-1]
        return parent.path + ((parent.key,) if parent.kind == "object" else (parent.index,))

    def _complete(self) -> None:
        if not self.frames:
            self.root_done = True
        else:
            parent = self.frames[-1]
            parent.state = "comma"
            if parent.kind == "array":
                parent.index += 1

    def _char(self, char: str) -> None:
        if self.token == "string":
            self._string(char)
            return
        if self.token == "primitive":
            if char not in ",]} \r\n\t":
                self.value += char
                return
            self._finish_primitive()
        if char.isspace():
            return
        if self.root_done:
            raise ValueError("AI 流 JSON 根值之后存在多余内容")
        frame = self.frames[-1] if self.frames else None
        if frame is not None:
            if frame.state in {"key", "first_key"}:
                if char == "}" and frame.state == "first_key":
                    self.frames.pop()
                    self._complete()
                    return
                if char != '"':
                    raise ValueError("AI 流 JSON 对象键必须为字符串")
                self._start_string(key=True)
                return
            if frame.state == "colon":
                if char != ":":
                    raise ValueError("AI 流 JSON 对象缺少冒号")
                frame.state = "value"
                return
            if frame.state == "comma":
                if char == ("}" if frame.kind == "object" else "]"):
                    self.frames.pop()
                    self._complete()
                    return
                if char != ",":
                    raise ValueError("AI 流 JSON 值之间缺少逗号")
                frame.state = "key" if frame.kind == "object" else "value"
                return
            if char == "]" and frame.kind == "array" and frame.state == "first_value":
                self.frames.pop()
                self._complete()
                return
        path = self._path()
        if char in "{[":
            self.frames.append(
                _Frame(
                    "object" if char == "{" else "array",
                    path,
                    "first_key" if char == "{" else "first_value",
                )
            )
        elif char == '"':
            self._start_string(key=False)
        elif char in "-0123456789tfn":
            self.token = "primitive"
            self.value = char
        else:
            raise ValueError("AI 流包含非法 JSON 值")

    def _start_string(self, *, key: bool) -> None:
        self.token = "string"
        self.token_path = self._path()
        self.key_token = key
        self.value = ""
        self.escape = False
        self.unicode_digits = None
        self.high_surrogate = None

    def _append(self, char: str) -> None:
        point = ord(char)
        if self.high_surrogate is not None:
            if not 0xDC00 <= point <= 0xDFFF:
                raise ValueError("AI 流包含未配对的 Unicode 代理项")
            char = chr(0x10000 + ((self.high_surrogate - 0xD800) << 10) + point - 0xDC00)
            self.high_surrogate = None
        elif 0xD800 <= point <= 0xDBFF:
            self.high_surrogate = point
            return
        elif 0xDC00 <= point <= 0xDFFF:
            raise ValueError("AI 流包含未配对的 Unicode 代理项")
        self.value += char
        if not self.key_token and visible_path(self.purpose, self.token_path):
            self.fields[".".join(map(str, self.token_path))] = self.value

    def _string(self, char: str) -> None:
        if self.unicode_digits is not None:
            if char not in "0123456789abcdefABCDEF":
                raise ValueError("AI 流包含非法 Unicode 转义")
            self.unicode_digits += char
            if len(self.unicode_digits) == 4:
                self._append(chr(int(self.unicode_digits, 16)))
                self.unicode_digits = None
            return
        if self.escape:
            self.escape = False
            if char == "u":
                self.unicode_digits = ""
            else:
                escapes = {
                    '"': '"',
                    "\\": "\\",
                    "/": "/",
                    "b": "\b",
                    "f": "\f",
                    "n": "\n",
                    "r": "\r",
                    "t": "\t",
                }
                if char not in escapes:
                    raise ValueError("AI 流包含非法 JSON 转义")
                self._append(escapes[char])
        elif char == "\\":
            self.escape = True
        elif char == '"':
            if self.high_surrogate is not None:
                raise ValueError("AI 流包含未配对的 Unicode 代理项")
            self.token = None
            if self.key_token:
                frame = self.frames[-1]
                if self.value in frame.keys:
                    raise ValueError("AI 流 JSON 对象键重复")
                frame.keys.add(self.value)
                frame.key = self.value
                frame.state = "colon"
            else:
                if self.token_path == ("action",):
                    self.action = self.value
                self._complete()
        elif ord(char) < 0x20:
            raise ValueError("AI 流 JSON 字符串包含控制字符")
        else:
            self._append(char)

    def _finish_primitive(self) -> None:
        value = json.loads(self.value)
        if isinstance(value, (dict, list, str)):
            raise ValueError("AI 流包含非法 JSON 原始值")
        self.token = None
        self._complete()
