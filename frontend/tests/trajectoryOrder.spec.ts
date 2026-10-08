import { describe, expect, it } from "vitest"

import { orderRunRecords } from "../src/utils/trajectoryOrder"
import type { EventType, TrajectoryRecord, TrajectoryRecordKind } from "../src/types/session-event"

const EVENT_TYPE_BY_KIND: Record<TrajectoryRecordKind, EventType> = {
  session: "session.started",
  user: "user.message",
  context: "context.added",
  model_request: "model.requested",
  model_response: "model.responded",
  model_error: "model.failed",
  state_change: "state.changed",
}

function record(eventSeq: number, kind: TrajectoryRecordKind): TrajectoryRecord {
  return {
    index: eventSeq,
    eventSeq,
    eventId: `evt_${eventSeq}`,
    eventType: EVENT_TYPE_BY_KIND[kind],
    kind,
    label: kind,
    summary: `${kind} #${eventSeq}`,
    fullText: `${kind} #${eventSeq}`,
    status: "complete",
    occurredAt: "2026-08-20T10:00:00Z",
    detail: {},
  }
}

function seqs(records: readonly TrajectoryRecord[]): number[] {
  return records.map((item) => item.eventSeq)
}

describe("orderRunRecords", () => {
  it("把学生输入移到携带它的模型请求之前，其余记录顺序不变", () => {
    // 事件追加顺序：学生 → 状态变化 → 上下文 → 模型请求 → 模型回复 → 上下文 → 模型请求。
    const ordered = orderRunRecords([
      record(1, "user"),
      record(2, "state_change"),
      record(3, "context"),
      record(4, "context"),
      record(5, "model_request"),
      record(6, "model_response"),
      record(7, "context"),
      record(8, "model_request"),
    ])

    expect(seqs(ordered)).toEqual([2, 3, 4, 1, 5, 6, 7, 8])
    // 序号仍是事件 seq，只改变了展示位置。
    expect(ordered.map((item) => item.eventSeq)).toEqual(seqs(ordered))
  })

  it("后面没有模型请求时学生输入留在原位", () => {
    const ordered = orderRunRecords([record(1, "user"), record(2, "state_change")])

    expect(seqs(ordered)).toEqual([1, 2])
  })

  it("同一请求前有多条学生输入时保持原有先后", () => {
    const ordered = orderRunRecords([
      record(1, "user"),
      record(2, "context"),
      record(3, "user"),
      record(4, "model_request"),
    ])

    expect(seqs(ordered)).toEqual([2, 1, 3, 4])
  })
})
