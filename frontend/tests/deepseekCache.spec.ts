import { describe, expect, it } from "vitest"

import { formatCacheHitRate, summarizeDeepSeekCache } from "../src/utils/deepseekCache"
import type { ModelResponseRecordDetail, TrajectoryRecord } from "../src/types/session-event"

function requestRecord(eventId: string, model: string): TrajectoryRecord {
  return {
    index: 1,
    eventSeq: 1,
    eventId,
    eventType: "model.requested",
    kind: "model_request",
    label: "模型请求",
    summary: `${model} · 1 条消息`,
    status: "complete",
    occurredAt: "2026-08-20T10:00:00Z",
    detail: {
      modelRequest: { provider: "OPENAI", model, messages: [], surfaceSeq: 1 },
    },
  }
}

function responseRecord(
  eventSeq: number,
  parentEventId: string | null,
  usage: Partial<ModelResponseRecordDetail>,
): TrajectoryRecord {
  return {
    index: eventSeq,
    eventSeq,
    eventId: `evt_resp_${eventSeq}`,
    eventType: "model.responded",
    kind: "model_response",
    label: "模型回复",
    summary: "valid",
    status: "complete",
    occurredAt: "2026-08-20T10:00:01Z",
    parentEventId,
    detail: { modelResponse: { output: {}, validation: "valid", ...usage } },
  }
}

const DEEPSEEK_USAGE: Partial<ModelResponseRecordDetail> = {
  inputTokens: 2766,
  outputTokens: 1460,
  promptCacheHitTokens: 384,
  promptCacheMissTokens: 2382,
}

describe("summarizeDeepSeekCache", () => {
  it("累加 DeepSeek 调用的命中与未命中 token，并按 hit / (hit + miss) 给出命中率", () => {
    const records = [
      requestRecord("req_1", "deepseek-flash"),
      responseRecord(2, "req_1", DEEPSEEK_USAGE),
      requestRecord("req_3", "deepseek/deepseek-v4.1-flash"),
      responseRecord(4, "req_3", {
        inputTokens: 1000,
        outputTokens: 200,
        promptCacheHitTokens: 100,
        promptCacheMissTokens: 900,
      }),
    ]

    const usage = summarizeDeepSeekCache(records)

    expect(usage).toEqual({
      models: ["deepseek-flash", "deepseek/deepseek-v4.1-flash"],
      callCount: 2,
      hitTokens: 484,
      missTokens: 3282,
      inputTokens: 3766,
      outputTokens: 1660,
    })
    expect(formatCacheHitRate(usage!)).toBe("12.9%")
  })

  it("非 DeepSeek 模型不计入，全部非 DeepSeek 时返回 undefined", () => {
    const records = [
      requestRecord("req_1", "~typesafe/jev-latest"),
      responseRecord(2, "req_1", DEEPSEEK_USAGE),
    ]

    expect(summarizeDeepSeekCache(records)).toBeUndefined()
  })

  it("DeepSeek 未返回 prompt_cache_* 字段时整条跳过，不按 0 命中计入", () => {
    const records = [
      requestRecord("req_1", "deepseek/deepseek-v4.1-flash"),
      responseRecord(2, "req_1", { inputTokens: 2862, outputTokens: 974 }),
    ]

    expect(summarizeDeepSeekCache(records)).toBeUndefined()
  })

  it("响应找不到配对的请求事件时不计入", () => {
    const records = [responseRecord(2, null, DEEPSEEK_USAGE)]

    expect(summarizeDeepSeekCache(records)).toBeUndefined()
  })

  it("命中为 0 的调用照常计入，命中率显示 0.0%", () => {
    const records = [
      requestRecord("req_1", "deepseek-flash"),
      responseRecord(2, "req_1", {
        inputTokens: 2253,
        outputTokens: 556,
        promptCacheHitTokens: 0,
        promptCacheMissTokens: 2253,
      }),
    ]

    const usage = summarizeDeepSeekCache(records)

    expect(usage?.callCount).toBe(1)
    expect(formatCacheHitRate(usage!)).toBe("0.0%")
  })

  it("合并多次运行的记录后按调用累加", () => {
    const firstRun = [
      requestRecord("req_1", "deepseek-flash"),
      responseRecord(2, "req_1", DEEPSEEK_USAGE),
    ]
    const secondRun = [
      requestRecord("req_11", "deepseek-flash"),
      responseRecord(12, "req_11", DEEPSEEK_USAGE),
    ]

    const usage = summarizeDeepSeekCache([...firstRun, ...secondRun])

    expect(usage?.callCount).toBe(2)
    expect(usage?.hitTokens).toBe(768)
    expect(usage?.missTokens).toBe(4764)
  })
})
