import type { TrajectoryRecord } from "../types/session-event"

/** 表头展示的 DeepSeek 缓存用量汇总。 */
export interface DeepSeekCacheUsage {
  /** 参与统计的模型名，同一运行里换过模型时会有多个。 */
  models: string[]
  callCount: number
  hitTokens: number
  missTokens: number
  inputTokens: number
  outputTokens: number
}

function usageCount(value: number | undefined): number | undefined {
  return typeof value === "number" ? value : undefined
}

function isDeepSeek(model: string): boolean {
  return model.toLowerCase().includes("deepseek")
}

/**
 * 汇总选定范围内的 DeepSeek 缓存用量；没有可计入的调用时返回 undefined，表头不渲染。
 *
 * 配对规则：model.responded 的 parentEventId 指向同一范围内的 model.requested，
 * 模型名取自那条请求事件（响应事件自身不记录 provider/model）。
 * 计入规则：DeepSeek 必须同时返回 prompt_cache_hit_tokens、prompt_cache_miss_tokens
 * 与输入/输出 token，且命中与未命中之和大于 0；缺字段的调用整条跳过，
 * 避免把“未返回缓存字段”当成 0 命中参与命中率。
 */
export function summarizeDeepSeekCache(
  records: readonly TrajectoryRecord[],
): DeepSeekCacheUsage | undefined {
  const modelByEventId = new Map<string, string>()
  for (const record of records) {
    const request = record.detail.modelRequest
    if (record.kind === "model_request" && request != null) {
      modelByEventId.set(record.eventId, request.model)
    }
  }

  const models = new Set<string>()
  let callCount = 0
  let hitTokens = 0
  let missTokens = 0
  let inputTokens = 0
  let outputTokens = 0

  for (const record of records) {
    if (record.kind !== "model_response" || record.parentEventId == null) continue
    const response = record.detail.modelResponse
    if (response == null) continue
    const model = modelByEventId.get(record.parentEventId)
    if (model === undefined || !isDeepSeek(model)) continue

    const hit = usageCount(response.promptCacheHitTokens)
    const miss = usageCount(response.promptCacheMissTokens)
    const input = usageCount(response.inputTokens)
    const output = usageCount(response.outputTokens)
    if (hit === undefined || miss === undefined || input === undefined || output === undefined) {
      continue
    }
    if (hit + miss === 0) continue

    models.add(model)
    callCount += 1
    hitTokens += hit
    missTokens += miss
    inputTokens += input
    outputTokens += output
  }

  if (callCount === 0) return undefined
  return { models: [...models], callCount, hitTokens, missTokens, inputTokens, outputTokens }
}

/** 命中率按 DeepSeek 口径 hit / (hit + miss) 计算，保留一位小数。 */
export function formatCacheHitRate(usage: DeepSeekCacheUsage): string {
  return `${((usage.hitTokens / (usage.hitTokens + usage.missTokens)) * 100).toFixed(1)}%`
}
