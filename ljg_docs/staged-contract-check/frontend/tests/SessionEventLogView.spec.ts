import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, describe, expect, it, vi } from "vitest"

import SessionEventLogView from "../src/views/SessionEventLogView.vue"
import type { Trajectory, TrajectoryRecord } from "../src/types/session-event"

function response(body: unknown) {
  return { ok: true, json: async () => body }
}

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/sessions/:sessionId/logs", component: SessionEventLogView },
      { path: "/sessions/:sessionId", component: { template: "<div />" } },
    ],
  })
  await router.push("/sessions/42/logs")
  await router.isReady()
  const wrapper = mount(SessionEventLogView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

function trajectoryPayload(): Trajectory {
  const records: TrajectoryRecord[] = [
    {
      index: 1,
      eventSeq: 1,
      eventId: "evt_1",
      eventType: "user.message",
      kind: "user",
      label: "学生",
      summary: "1 加 1 等于 2。",
      fullText: "1 加 1 等于 2。",
      status: "complete",
      occurredAt: "2026-08-20T10:00:01Z",
      detail: { user: { text: "1 加 1 等于 2。", inputType: "text" } },
    },
    {
      index: 2,
      eventSeq: 2,
      eventId: "evt_2",
      eventType: "context.added",
      kind: "context",
      label: "上下文",
      summary: 'question · question:1 · { "questionContent": "计算 1 + 1。" }',
      fullText: 'question · question:1\n{\n  "questionContent": "计算 1 + 1。"\n}',
      status: "complete",
      occurredAt: "2026-08-20T10:00:02Z",
      parentEventId: "evt_1",
      detail: {
        context: { kind: "question", source: "question:1", content: { questionContent: "计算 1 + 1。" } },
      },
    },
    {
      index: 3,
      eventSeq: 3,
      eventId: "evt_3",
      eventType: "model.requested",
      kind: "model_request",
      label: "模型请求",
      summary: "test-model · 1 条消息 · surfaceSeq #2",
      fullText: "[user]\n请评价",
      status: "complete",
      occurredAt: "2026-08-20T10:00:03Z",
      parentEventId: "evt_2",
      detail: {
        modelRequest: {
          provider: "test-ai",
          model: "test-model",
          messages: [{ role: "user", content: "请评价" }],
          surfaceSeq: 2,
        },
      },
    },
    {
      index: 4,
      eventSeq: 4,
      eventId: "evt_4",
      eventType: "model.responded",
      kind: "model_response",
      label: "模型回复",
      summary: "correctness=CORRECT · valid",
      fullText: '{\n  "correctness": "CORRECT",\n  "missingPoints": []\n}',
      status: "complete",
      durationMs: 1200,
      occurredAt: "2026-08-20T10:00:04Z",
      parentEventId: "evt_3",
      detail: {
        modelResponse: {
          output: { correctness: "CORRECT" },
          rawContent: '{"correctness":"CORRECT"}',
          validation: "valid",
        },
      },
    },
    {
      index: 5,
      eventSeq: 5,
      eventId: "evt_5",
      eventType: "state.changed",
      kind: "state_change",
      label: "状态变化",
      summary: "AI_EVALUATING → WAIT_STUDENT_ACTION",
      fullText: "AI_EVALUATING → WAIT_STUDENT_ACTION\n原因：done",
      status: "complete",
      occurredAt: "2026-08-20T10:00:05Z",
      parentEventId: "evt_4",
      detail: { stateChange: { from: "AI_EVALUATING", to: "WAIT_STUDENT_ACTION", reason: "done" } },
    },
  ]
  return {
    sessionId: 42,
    runs: [
      {
        runId: "run-1",
        startedAt: "2026-08-20T10:00:01Z",
        steps: [{ kind: "user_input", eventSeq: 1, summary: "学生提交自讲" }],
        records,
      },
    ],
    events: records,
  }
}

async function openTab(wrapper: ReturnType<typeof mount>, label: string) {
  const tab = wrapper.findAll('[role="tab"]').find((candidate) => candidate.text() === label)
  if (tab === undefined) throw new Error(`缺少页签：${label}`)
  await tab.trigger("click")
  await flushPromises()
}

async function showAllRecords(wrapper: ReturnType<typeof mount>) {
  const button = wrapper
    .findAll("button.toolbar-button")
    .find((candidate) => candidate.text() === "显示完整日志")
  if (button === undefined) throw new Error("缺少「显示完整日志」按钮")
  await button.trigger("click")
  await flushPromises()
}

describe("SessionEventLogView", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("默认只展示上下文、用户与助手记录，并统计被隐藏的记录数", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(trajectoryPayload()))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith("/api/sessions/42/trajectory", expect.any(Object))
    // 5 条记录中隐藏「模型请求」与「状态变化」，只留用户、上下文、模型回复。
    expect(wrapper.findAll("div.record-row")).toHaveLength(3)
    expect(wrapper.text()).toContain("已按精简范围隐藏 2 条状态变化与模型请求记录")
    expect(wrapper.text()).toContain("1 加 1 等于 2。")
    expect(wrapper.text()).toContain("question · question:1")
    expect(wrapper.text()).toContain("correctness=CORRECT · valid")
    expect(wrapper.text()).toContain("1.20 s")
    expect(
      wrapper.findAll("div.record-row").map((row) => row.attributes("data-kind")),
    ).toEqual(["user", "context", "model_response"])
    expect(wrapper.text()).not.toContain("test-model · 1 条消息")
    // 界面只保留轨迹：不再出现 Surface / Trace 视图切换。
    expect(wrapper.text()).not.toContain("Trace 因果关系")
    expect(wrapper.text()).not.toContain("Surface 模型上下文")

    await showAllRecords(wrapper)
    expect(wrapper.findAll("div.record-row")).toHaveLength(5)
    expect(wrapper.text()).toContain("test-model · 1 条消息 · surfaceSeq #2")
    expect(wrapper.text()).toContain("AI_EVALUATING → WAIT_STUDENT_ACTION")
  })

  it("没有耗时的记录显示“未记录”，不显示 null ms", async () => {
    const payload = trajectoryPayload()
    payload.runs[0].records[0] = { ...payload.runs[0].records[0], durationMs: null }
    const fetchMock = vi.fn().mockResolvedValueOnce(response(payload))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()

    expect(wrapper.text()).not.toContain("null ms")
    expect(wrapper.find("div.record-row").text()).toContain("未记录")
  })

  it("展开后显示未压缩的完整原文，而不是带省略号的摘要", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(trajectoryPayload()))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()
    const contextRow = wrapper.findAll("div.record-row")[1]
    expect(contextRow.find("pre.record-full").exists()).toBe(false)

    await contextRow.get("button.expand-button").trigger("click")

    // 完整原文保留 JSON 缩进换行，且不含摘要在截断时追加的省略号。
    const full = contextRow.get("pre.record-full").text()
    expect(full).toBe('question · question:1\n{\n  "questionContent": "计算 1 + 1。"\n}')
    expect(full).not.toContain("…")

    await contextRow.get("button.expand-button").trigger("click")
    expect(contextRow.find("pre.record-full").exists()).toBe(false)
  })

  it("后端响应缺少 fullText 时展开仍可用，不因 undefined.length 抛错", async () => {
    const payload = trajectoryPayload()
    // 模拟前后端版本不一致：旧后端不会返回 fullText。
    const records = payload.runs[0].records.map((record) => {
      const { fullText: _dropped, ...rest } = record
      return rest as TrajectoryRecord
    })
    payload.runs[0].records = records
    payload.events = records
    const fetchMock = vi.fn().mockResolvedValueOnce(response(payload))
    vi.stubGlobal("fetch", fetchMock)
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {})

    const wrapper = await mountView()
    const row = wrapper.findAll("div.record-row")[0]
    await row.get("button.expand-button").trigger("click")
    await flushPromises()

    expect(errorSpy).not.toHaveBeenCalled()
    // 退化成摘要，但展开区必须真的出现。
    expect(row.find("pre.record-full").text()).toContain("1 加 1 等于 2。")
    // 明确说明这是降级显示，且不提供复制，避免把被截断的摘要当成全文复制走。
    expect(row.get(".record-full-size").text()).toContain("后端未返回完整原文")
    expect(row.find("button.copy-button").exists()).toBe(false)

    errorSpy.mockRestore()
  })

  it("展开区提供复制全文，并显示完整正文长度", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(trajectoryPayload()))
    vi.stubGlobal("fetch", fetchMock)
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    })

    const wrapper = await mountView()
    const contextRow = wrapper.findAll("div.record-row")[1]
    await contextRow.get("button.expand-button").trigger("click")

    // 长度按完整原文统计，不是被截断的摘要。
    expect(contextRow.get(".record-full-size").text()).toBe(
      `${'question · question:1\n{\n  "questionContent": "计算 1 + 1。"\n}'.length} 字符`,
    )
    await contextRow.get("button.copy-button").trigger("click")
    await flushPromises()

    expect(writeText).toHaveBeenCalledWith('question · question:1\n{\n  "questionContent": "计算 1 + 1。"\n}')
    expect(contextRow.get("button.copy-button").text()).toBe("已复制")
  })

  it("模型回复展开后按原始 JSON 换行展示", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(trajectoryPayload()))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()
    const responseRow = wrapper.findAll("div.record-row")[2]
    await responseRow.get("button.expand-button").trigger("click")

    const lines = responseRow.get("pre.record-full").text().split("\n")
    expect(lines).toEqual(["{", '  "correctness": "CORRECT",', '  "missingPoints": []', "}"])
  })

  it("点击记录行后展示结构化详情，并能跳转到父事件", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(trajectoryPayload()))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()
    expect(wrapper.find("aside.details").exists()).toBe(false)

    await showAllRecords(wrapper)
    await wrapper.findAll("div.record-row")[2].trigger("click")
    await flushPromises()

    const details = wrapper.get("aside.details")
    expect(details.text()).toContain("模型请求")
    expect(details.findAll('[role="tab"]').map((tab) => tab.text())).toEqual([
      "概述",
      "消息（1）",
      "模型上下文",
      "原始 JSON",
    ])
    // 概述页给出层级导航：父事件与直接结果都可点击跳转。
    expect(details.text()).toContain("#2 上下文")
    expect(details.text()).toContain("#4 模型回复")

    await openTab(wrapper, "消息（1）")
    expect(wrapper.get("aside.details").text()).toContain("test-ai / test-model · 1 条消息")
    expect(wrapper.get("aside.details").text()).toContain("请评价")

    await openTab(wrapper, "概述")
    await wrapper.get("aside.details").findAll("button.link")[0].trigger("click")
    await flushPromises()
    expect(wrapper.get("aside.details").text()).toContain("上下文")
    expect(wrapper.get("aside.details").text()).toContain("#2")
  })

  it("模型请求详情可按 surfaceSeq 读取模型上下文", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(trajectoryPayload()))
      .mockResolvedValueOnce(
        response({
          sessionId: 42,
          asOfSeq: 2,
          messages: [{ seq: 1, role: "user", content: "1 加 1 等于 2。" }],
          contexts: [
            { seq: 2, kind: "question", source: "question:1", content: { questionContent: "计算 1 + 1。" } },
          ],
        }),
      )
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()
    await showAllRecords(wrapper)
    await wrapper.findAll("div.record-row")[2].trigger("click")
    await flushPromises()

    await openTab(wrapper, "模型上下文")

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/sessions/42/surface?asOfSeq=2",
      expect.any(Object),
    )
    const details = wrapper.get("aside.details")
    expect(details.text()).toContain("1 加 1 等于 2。")
    expect(details.text()).toContain("question")
    expect(details.text()).toContain("计算 1 + 1。")
  })

  it("历史模型回复缺少 rawContent 时给出明确说明而不是空白", async () => {
    const payload = trajectoryPayload()
    const records = payload.runs[0].records
    records[3] = {
      ...records[3],
      detail: {
        modelResponse: {
          output: { correctness: "CORRECT" },
          validation: "valid",
        },
      },
    }
    payload.events = records
    const fetchMock = vi.fn().mockResolvedValueOnce(response(payload))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()
    // 默认精简范围下，模型回复是第 3 行。
    await wrapper.findAll("div.record-row")[2].trigger("click")
    await flushPromises()
    await openTab(wrapper, "输出")

    const details = wrapper.get("aside.details")
    expect(details.text()).toContain("correctness")
    expect(details.text()).toContain("该历史事件未保存模型原始回复。")
  })

  it("搜索高亮命中记录，收起运行后只保留一行摘要", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(trajectoryPayload()))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()
    await wrapper.get('input[aria-label="搜索轨迹"]').setValue("模型")
    await flushPromises()

    // 精简范围下只有「模型回复」命中，「模型请求」已被范围过滤掉。
    expect(wrapper.text()).toContain("搜索「模型」命中 1 / 3 条记录")
    expect(wrapper.findAll("div.record-row.matched")).toHaveLength(1)

    await wrapper.findAll("button.toolbar-button")[0].trigger("click")
    await flushPromises()

    expect(wrapper.findAll("div.record-row")).toHaveLength(0)
    expect(wrapper.get("div.group-row").text()).toContain("已收起")
    expect(wrapper.get("div.group-row").text()).toContain("当前范围 3 条记录")
  })
})
