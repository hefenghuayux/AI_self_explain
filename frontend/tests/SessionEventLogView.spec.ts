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
      summary: "question · question:1",
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

describe("SessionEventLogView", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("只读取 trajectory，并把同一批事件渲染成记录账本", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(trajectoryPayload()))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith("/api/sessions/42/trajectory", expect.any(Object))
    expect(wrapper.findAll("tr.record-row")).toHaveLength(5)
    expect(wrapper.text()).toContain("1 加 1 等于 2。")
    expect(wrapper.text()).toContain("question · question:1")
    expect(wrapper.text()).toContain("test-model · 1 条消息 · surfaceSeq #2")
    expect(wrapper.text()).toContain("correctness=CORRECT · valid")
    expect(wrapper.text()).toContain("AI_EVALUATING → WAIT_STUDENT_ACTION")
    expect(wrapper.text()).toContain("1.20 s")
    // 界面只保留轨迹：不再出现 Surface / Trace 视图切换。
    expect(wrapper.text()).not.toContain("Trace 因果关系")
    expect(wrapper.text()).not.toContain("Surface 模型上下文")
  })

  it("点击记录行后展示结构化详情，并能跳转到父事件", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(trajectoryPayload()))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()
    expect(wrapper.find("aside.details").exists()).toBe(false)

    await wrapper.findAll("tr.record-row")[2].trigger("click")
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
    await wrapper.findAll("tr.record-row")[2].trigger("click")
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
    await wrapper.findAll("tr.record-row")[3].trigger("click")
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

    expect(wrapper.text()).toContain("搜索「模型」命中 2 / 5 条记录")
    expect(wrapper.findAll("tr.record-row.matched")).toHaveLength(2)

    await wrapper.get("button.toolbar-button").trigger("click")
    await flushPromises()

    expect(wrapper.findAll("tr.record-row")).toHaveLength(0)
    expect(wrapper.get("tr.group-row").text()).toContain("已收起")
    expect(wrapper.get("tr.group-row").text()).toContain("5 条记录")
  })
})
