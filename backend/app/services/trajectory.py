import json
from collections import defaultdict

from sqlalchemy.orm import Session as DatabaseSession

from app.models.session_event import SessionEvent
from app.schemas.session_event import (
    ContextAddedData,
    ModelFailedData,
    ModelRequestedData,
    StateChangedData,
    UserMessageData,
)
from app.schemas.session_projection import (
    ContextRecordDetail,
    ModelCallStep,
    ModelErrorDetail,
    ModelRequestDetail,
    ModelResponseDetail,
    SessionRecordDetail,
    StateChangeDetail,
    StateChangeStep,
    Trajectory,
    TrajectoryRecord,
    TrajectoryRecordDetail,
    TrajectoryRecordKind,
    TrajectoryRecordStatus,
    TrajectoryRun,
    TrajectoryStep,
    UserInputStep,
    UserRecordDetail,
)
from app.services.event_store import EventStore

# 账本收起时单行摘要的显示上限。摘要是压缩过的预览，完整内容另见 fullText。
SUMMARY_LIMIT = 200
LABEL_LIMIT = 80
# 摘要里最多取几个标量字段；容器不参与摘要，避免出现“N 项”这类计数替代品。
OUTPUT_SUMMARY_FIELDS = 3
# model.requested 全文展示的消息正文上限；超长提示词只截这一处，避免整条记录不可读。
MESSAGE_PREVIEW_LIMIT = 4000

KIND_BY_EVENT_TYPE: dict[str, TrajectoryRecordKind] = {
    "session.started": "session",
    "user.message": "user",
    "context.added": "context",
    "model.requested": "model_request",
    "model.responded": "model_response",
    "model.failed": "model_error",
    "state.changed": "state_change",
}

LABEL_BY_KIND: dict[TrajectoryRecordKind, str] = {
    "session": "会话",
    "user": "学生",
    "context": "上下文",
    "model_request": "模型请求",
    "model_response": "模型回复",
    "model_error": "模型失败",
    "state_change": "状态变化",
}


def _truncate(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}…"


def _summary_value(value: object) -> str | None:
    """单行摘要只接受标量；容器交给 fullText 完整展示，不做计数替代。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _summarize_output(output: dict[str, object]) -> str:
    parts: list[str] = []
    for key, value in output.items():
        rendered = _summary_value(value)
        if rendered is None:
            continue
        parts.append(f"{key}={rendered}")
        if len(parts) == OUTPUT_SUMMARY_FIELDS:
            break
    return " · ".join(parts)


def _pretty_json(value: object) -> str:
    """按 JSON 缩进输出；已经是字符串的内容保持原样，不二次包引号。"""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _model_response_full_text(data: dict[str, object]) -> str:
    """模型原始回复优先；历史事件没有 rawContent 时退回判词 JSON。

    两者都按原文换行展示，不压成一行，也不改写成“N 个字段”。
    """
    raw_content = data.get("rawContent")
    if isinstance(raw_content, str) and raw_content.strip() != "":
        return raw_content
    return _pretty_json(data.get("output"))


def _message_full_text(message: dict[str, object]) -> str:
    role = message.get("role")
    content = message.get("content")
    text = content if isinstance(content, str) else _pretty_json(content)
    if len(text) > MESSAGE_PREVIEW_LIMIT:
        text = (
            f"{text[:MESSAGE_PREVIEW_LIMIT]}…"
            f"（该消息正文超过 {MESSAGE_PREVIEW_LIMIT} 字符，已截断）"
        )
    return f"[{role if isinstance(role, str) else 'unknown'}]\n{text}"


def _normalize_detail(detail: TrajectoryRecordDetail) -> TrajectoryRecordDetail:
    """detail 只保留本次记录真正使用的那一个键。

    否则未使用的键会以 null 出现，而前端按“键是否存在”决定展示哪些页签。
    """
    return TrajectoryRecordDetail.model_validate(detail.model_dump(exclude_none=True))


def _model_response_detail(data: dict[str, object]) -> TrajectoryRecordDetail:
    """读取路径只强制校验必需字段。

    rawContent 是 commit 46e3466 才加入的展示字段，更早写入的历史事件没有它；
    用 ModelRespondedData 整体校验会因为这些历史事件让整个投影抛异常。
    """
    output = data.get("output")
    validation = data.get("validation")
    if not isinstance(output, dict):
        raise ValueError("model.responded.data.output 必须是 JSON object")
    if validation not in {"valid", "invalid"}:
        raise ValueError(f"model.responded.data.validation 取值非法：{validation!r}")
    raw_content = data.get("rawContent")
    return TrajectoryRecordDetail(
        model_response=ModelResponseDetail(
            output=output,
            raw_content=raw_content if isinstance(raw_content, str) else None,
            validation=validation,
            input_tokens=_optional_count(data.get("inputTokens")),
            output_tokens=_optional_count(data.get("outputTokens")),
        )
    )


def _optional_count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _recorded_duration_ms(data: dict[str, object]) -> int | None:
    return _optional_count(data.get("durationMs"))


def _index_results(events: list[SessionEvent]) -> dict[str, list[SessionEvent]]:
    """按 parent_event_id 建立"请求 -> 直接结果"索引，不做时间邻近推断。"""
    results_by_request: dict[str, list[SessionEvent]] = defaultdict(list)
    for event in events:
        if event.event_type in {"model.responded", "model.failed"}:
            if event.parent_event_id is not None:
                results_by_request[event.parent_event_id].append(event)
    return results_by_request


def _request_status(
    request: SessionEvent,
    results_by_request: dict[str, list[SessionEvent]],
) -> TrajectoryRecordStatus:
    results = results_by_request.get(request.event_id, [])
    if len(results) > 1:
        raise ValueError(f"模型请求存在多个直接结果事件：{request.event_id}")
    if not results:
        return "pending"
    return "failed" if results[0].event_type == "model.failed" else "complete"


class TrajectoryService:
    def __init__(self, database_session: DatabaseSession) -> None:
        self.event_store = EventStore(database_session)

    def build_trajectory(self, session_id: int) -> Trajectory:
        all_events = self.event_store.list_events(session_id)
        results_by_request = _index_results(all_events)

        events_by_run: dict[str, list[SessionEvent]] = defaultdict(list)
        for event in all_events:
            if event.run_id is not None:
                events_by_run[event.run_id].append(event)

        runs = [
            self._build_run(run_id, events)
            for run_id, events in sorted(events_by_run.items(), key=lambda item: item[1][0].seq)
        ]
        return Trajectory(
            session_id=session_id,
            runs=tuple(runs),
            events=tuple(
                self._build_record(index, event, results_by_request)
                for index, event in enumerate(all_events, start=1)
            ),
        )

    def _build_run(self, run_id: str, events: list[SessionEvent]) -> TrajectoryRun:
        # 运行内部的请求状态只由本运行的事件决定，不跨运行推断。
        results_by_request = _index_results(events)
        steps: list[tuple[int, TrajectoryStep]] = []
        for event in events:
            if event.event_type == "user.message":
                steps.append(
                    (
                        event.seq,
                        UserInputStep(event_seq=event.seq, summary="学生提交自讲"),
                    )
                )
            elif event.event_type == "model.requested":
                steps.append((event.seq, self._model_call_step(event, results_by_request)))
            elif event.event_type == "state.changed":
                data = StateChangedData.model_validate(event.data)
                steps.append(
                    (
                        event.seq,
                        StateChangeStep(event_seq=event.seq, from_=data.from_, to=data.to),
                    )
                )

        steps.sort(key=lambda item: item[0])
        return TrajectoryRun(
            run_id=run_id,
            started_at=events[0].occurred_at,
            steps=tuple(step for _, step in steps),
            records=tuple(
                self._build_record(index, event, results_by_request)
                for index, event in enumerate(events, start=1)
            ),
        )

    def _build_record(
        self,
        index: int,
        event: SessionEvent,
        results_by_request: dict[str, list[SessionEvent]],
    ) -> TrajectoryRecord:
        kind = KIND_BY_EVENT_TYPE[event.event_type]
        status: TrajectoryRecordStatus = "complete"
        summary: str
        full_text: str
        duration_ms: int | None = None
        detail: TrajectoryRecordDetail

        if event.event_type == "user.message":
            data = UserMessageData.model_validate(event.data)
            full_text = data.text
            summary = _truncate(data.text, SUMMARY_LIMIT)
            detail = TrajectoryRecordDetail(
                user=UserRecordDetail(text=data.text, input_type=data.inputType)
            )
        elif event.event_type == "context.added":
            data = ContextAddedData.model_validate(event.data)
            full_text = f"{data.kind} · {data.source}\n{_pretty_json(data.content)}"
            summary = _truncate(
                f"{data.kind} · {data.source} · {' '.join(_pretty_json(data.content).split())}",
                SUMMARY_LIMIT,
            )
            detail = TrajectoryRecordDetail(
                context=ContextRecordDetail(
                    kind=data.kind, source=data.source, content=data.content
                )
            )
        elif event.event_type == "model.requested":
            data = ModelRequestedData.model_validate(event.data)
            messages = tuple(message.model_dump(mode="json") for message in data.messages)
            message_count = len(messages)
            status = _request_status(event, results_by_request)
            full_text = "\n\n".join(_message_full_text(message) for message in messages)
            summary = _truncate(
                f"{data.model} · {message_count} 条消息 · surfaceSeq #{data.surfaceSeq}",
                SUMMARY_LIMIT,
            )
            detail = TrajectoryRecordDetail(
                model_request=ModelRequestDetail(
                    provider=data.provider,
                    model=data.model,
                    messages=messages,
                    surface_seq=data.surfaceSeq,
                )
            )
        elif event.event_type == "model.responded":
            detail = _model_response_detail(event.data)
            output = detail.model_response.output if detail.model_response is not None else {}
            validation = (
                detail.model_response.validation if detail.model_response is not None else "invalid"
            )
            full_text = _model_response_full_text(event.data)
            summary_fields = _summarize_output(output)
            summary = _truncate(
                f"{summary_fields} · {validation}" if summary_fields else validation,
                SUMMARY_LIMIT,
            )
            duration_ms = _recorded_duration_ms(event.data)
        elif event.event_type == "model.failed":
            data = ModelFailedData.model_validate(event.data)
            full_text = f"{data.errorType}\n{data.message}"
            summary = _truncate(f"{data.errorType} · {data.message}", SUMMARY_LIMIT)
            status = "failed"
            duration_ms = data.durationMs
            detail = TrajectoryRecordDetail(
                model_error=ModelErrorDetail(errorType=data.errorType, message=data.message)
            )
        elif event.event_type == "state.changed":
            data = StateChangedData.model_validate(event.data)
            full_text = f"{data.from_} → {data.to}\n原因：{data.reason}"
            summary = _truncate(f"{data.from_} → {data.to}", SUMMARY_LIMIT)
            detail = TrajectoryRecordDetail(
                state_change=StateChangeDetail(
                    from_=data.from_, to=data.to, reason=data.reason
                )
            )
        else:
            full_text = "会话开始"
            summary = "会话开始"
            detail = TrajectoryRecordDetail(session=SessionRecordDetail())

        return TrajectoryRecord(
            index=index,
            event_seq=event.seq,
            event_id=event.event_id,
            event_type=event.event_type,
            kind=kind,
            label=LABEL_BY_KIND[kind],
            summary=summary,
            full_text=full_text,
            status=status,
            duration_ms=duration_ms,
            occurred_at=event.occurred_at,
            parent_event_id=event.parent_event_id,
            detail=_normalize_detail(detail),
        )

    def _model_call_step(
        self,
        request: SessionEvent,
        results_by_request: dict[str, list[SessionEvent]],
    ) -> ModelCallStep:
        results = results_by_request.get(request.event_id, [])
        if len(results) > 1:
            raise ValueError(f"模型请求存在多个直接结果事件：{request.event_id}")
        if not results:
            return ModelCallStep(request_seq=request.seq, status="pending")

        result = results[0]
        if result.event_type == "model.failed":
            status = "failed"
        else:
            status = "success"
        return ModelCallStep(
            request_seq=request.seq,
            result_seq=result.seq,
            status=status,
            duration_ms=_recorded_duration_ms(result.data),
        )
