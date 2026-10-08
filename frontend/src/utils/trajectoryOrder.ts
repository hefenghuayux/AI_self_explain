import type { TrajectoryRecord } from "../types/session-event"

/**
 * 运行内展示顺序：把学生输入移到携带它的那条模型请求之前。
 *
 * 事件追加顺序是“学生输入 → 上下文 → 模型请求”，而真正发送给模型的消息把学生输入
 * 放在最后一层 messages[4]，题目上下文与共享历史都在它前面（见
 * `ljg_docs/12-提示词共享前缀/01-共享前缀对照草案.md` 第五节与
 * `backend/app/services/ai_support.py` 的 `_model_request`）。账本按事件序直接渲染
 * 会显示成“学生 → 上下文”，与缓存友好的真实发送顺序相反。
 *
 * 只做一次搬移：
 * - 其余记录的相对顺序不变，模型请求与它那组上下文的配对不会被打散。
 * - `eventSeq` 保持原值，仍能直接对照 `session_events.seq`，因此一屏内序号不单调。
 * - 后面没有模型请求的学生输入留在原位置，它没有被任何请求携带。
 */
export function orderRunRecords(records: readonly TrajectoryRecord[]): TrajectoryRecord[] {
  // 倒序扫描：只有后面还存在模型请求的学生输入才需要后移。
  const carried = new Set<number>()
  let requestSeen = false
  for (let index = records.length - 1; index >= 0; index -= 1) {
    if (records[index].kind === "model_request") requestSeen = true
    else if (requestSeen && records[index].kind === "user") carried.add(index)
  }

  const ordered: TrajectoryRecord[] = []
  const pending: TrajectoryRecord[] = []
  for (const [index, record] of records.entries()) {
    if (carried.has(index)) {
      pending.push(record)
      continue
    }
    // 每条被携带的学生输入后面都有模型请求，pending 一定在这里被取走。
    if (record.kind === "model_request") {
      ordered.push(...pending)
      pending.length = 0
    }
    ordered.push(record)
  }
  return ordered
}
