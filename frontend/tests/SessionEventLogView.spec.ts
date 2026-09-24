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

const DETAIL_KEYS = [
  "session",
  "user",
  "context",
  "modelRequest",
  "modelResponse",
  "modelError",
  "stateChange",
] as const

/** 旧后端把未使用的 detail 键序列化成 null，而不是省略；线上响应就是这个形状。 */
function withNullDetails(payload: Trajectory): Trajectory {
  const fill = (record: TrajectoryRecord): TrajectoryRecord => {
    const detail = record.detail as Record<string, unknown>
    return {
      ...record,
      detail: Object.fromEntries(DETAIL_KEYS.map((key) => [key, detail[key] ?? null])) as
        TrajectoryRecord["detail"],
    }
  }
  return {
    ...payload,
    runs: payload.runs.map((run) => ({ ...run, records: run.records.map(fill) })),
    events: payload.events.map(fill),
  }
}

/** 两次运行的会话：第 1 次是自讲闭环，第 2 次是它的后续运行。 */
function twoRunPayload(): Trajectory {
  const payload = trajectoryPayload()
  const secondRecords = payload.runs[0].records.map((record) => ({
    ...record,
    eventSeq: record.eventSeq + 10,
    eventId: `${record.eventId}_second`,
  }))
  return {
    sessionId: payload.sessionId,
    runs: [
      payload.runs[0],
      {
        runId: "run-2",
        startedAt: "2026-08-20T11:00:00Z",
        steps: [],
        records: secondRecords,
      },
    ],
    events: [...payload.events, ...secondRecords],
  }
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

  it("点击记录行只高亮该行，详情改由展开区承载", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(trajectoryPayload()))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()
    expect(wrapper.find("aside.details").exists()).toBe(false)

    await showAllRecords(wrapper)
    await wrapper.findAll("div.record-row")[2].trigger("click")
    await flushPromises()

    // 详情面板已移除：点击只做高亮，不再渲染任何页签容器。
    expect(wrapper.find("aside.details").exists()).toBe(false)
    expect(wrapper.findAll('[role="tab"]')).toHaveLength(0)
    expect(wrapper.findAll("div.record-row.selected")).toHaveLength(1)
    expect(wrapper.get("div.record-row.selected").attributes("data-kind")).toBe("model_request")
  })

  it("时间线色块跟随账本范围，精简范围不显示状态变化与模型请求", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(trajectoryPayload()))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()

    // 色块与账本行同源：5 条记录里精简范围只有 3 条，色块也必须是 3 个。
    expect(
      wrapper.findAll("button.timeline-block").map((block) => block.attributes("data-kind")),
    ).toEqual(["user", "context", "model_response"])

    await showAllRecords(wrapper)

    expect(wrapper.findAll("button.timeline-block")).toHaveLength(5)
    expect(wrapper.findAll("button.timeline-block")[4].attributes("data-kind")).toBe("state_change")
  })

  it("切回精简范围后账本与色块同步收敛，不残留被隐藏记录的选中态", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(trajectoryPayload()))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()
    await showAllRecords(wrapper)
    // 完整范围下第 5 行是状态变化，精简范围会把它藏掉。
    await wrapper.findAll("div.record-row")[4].trigger("click")
    await flushPromises()
    expect(wrapper.findAll("div.record-row.selected")).toHaveLength(1)

    const backButton = wrapper
      .findAll("button.toolbar-button")
      .find((candidate) => candidate.text() === "只看上下文与助手")
    if (backButton === undefined) throw new Error("缺少「只看上下文与助手」按钮")
    await backButton.trigger("click")
    await flushPromises()

    expect(wrapper.findAll("button.timeline-block")).toHaveLength(3)
    expect(wrapper.findAll("div.record-row")).toHaveLength(3)
    // 被范围隐藏的记录不再出现在账本里，因此也没有残留高亮。
    expect(wrapper.findAll("div.record-row.selected")).toHaveLength(0)
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

  it("detail 未使用的键是显式 null 时轨迹页仍能渲染，展开按钮继续生效", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(withNullDetails(trajectoryPayload())))
    vi.stubGlobal("fetch", fetchMock)
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {})

    const wrapper = await mountView()

    // 渲染期抛错会打断组件树的 patch，之后所有按钮都失效。
    expect(errorSpy).not.toHaveBeenCalled()
    expect(wrapper.findAll("div.record-row")).toHaveLength(3)

    await showAllRecords(wrapper)
    expect(wrapper.findAll("div.record-row")).toHaveLength(5)

    await wrapper.findAll("div.record-row")[1].get("button.expand-button").trigger("click")
    await flushPromises()
    expect(wrapper.findAll("pre.record-full")).toHaveLength(1)
    expect(errorSpy).not.toHaveBeenCalled()

    errorSpy.mockRestore()
  })

  it("默认选中最后一次运行，切到「全部运行」后按事件序合并所有运行", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(twoRunPayload()))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()
    expect((wrapper.get("select").element as HTMLSelectElement).value).toBe("run-2")
    expect(wrapper.findAll("div.record-row")).toHaveLength(3)
    expect(wrapper.get(".section-note").text()).toContain("第 2 次运行")

    const allOption = wrapper
      .findAll("option")
      .find((option) => option.text().startsWith("全部运行"))
    if (allOption === undefined) throw new Error("缺少「全部运行」选项")
    await wrapper.get("select").setValue(allOption.attributes("value")!)
    await flushPromises()

    // 两次运行各 5 条记录，精简范围各留 3 条；合并后按事件序排列。
    expect(wrapper.findAll("div.record-row")).toHaveLength(6)
    expect(wrapper.findAll("div.record-row").map((row) => row.find(".record-index").text())).toEqual([
      "#1",
      "#2",
      "#4",
      "#11",
      "#12",
      "#14",
    ])
    const note = wrapper.get(".section-note").text()
    expect(note).toContain("全部运行")
    expect(note).toContain("共 10 条记录")
  })
})
