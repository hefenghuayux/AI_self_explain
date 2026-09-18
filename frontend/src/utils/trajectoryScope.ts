import type { TrajectoryRecord, TrajectoryRecordKind } from "../types/session-event"

export type TrajectoryScope = "core" | "all"

/** 精简范围：只保留上下文、用户与助手（模型）信息，隐藏状态变化和模型请求。 */
const CORE_KINDS: readonly TrajectoryRecordKind[] = [
  "session",
  "user",
  "context",
  "model_response",
  "model_error",
]

/**
 * 账本与时间线共用同一份范围规则。
 *
 * 两边各过滤一次会让时间线多出账本已隐藏的色块，点它定位不到任何记录，
 * 所以范围判定必须只有一个来源。
 */
export function scopeRecords(
  records: readonly TrajectoryRecord[],
  scope: TrajectoryScope,
): TrajectoryRecord[] {
  return scope === "core" ? records.filter((record) => CORE_KINDS.includes(record.kind)) : records.slice()
}
