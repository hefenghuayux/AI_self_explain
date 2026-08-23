import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, describe, expect, it, vi } from "vitest"

import SessionEventLogView from "../src/views/SessionEventLogView.vue"

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

describe("SessionEventLogView", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("按 Trajectory 展示步骤，并在展开时按 seq 读取原始事件", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({
        sessionId: 42,
        runs: [{
          runId: "run-1",
          startedAt: "2026-08-20T10:00:00Z",
          steps: [
            { kind: "user_input", eventSeq: 1, summary: "学生提交自讲" },
            { kind: "model_call", requestSeq: 3, resultSeq: 4, status: "success", durationMs: 1200 },
            { kind: "state_change", eventSeq: 5, from: "EVALUATING", to: "WAIT_STUDENT_ACTION" },
          ],
        }],
      }))
      .mockResolvedValueOnce(response({
        sessionId: 42,
        seq: 3,
        eventId: "evt-3",
        runId: "run-1",
        eventType: "model.requested",
        occurredAt: "2026-08-20T10:00:03Z",
        data: { provider: "test", model: "test-model", messages: [], surfaceSeq: 2 },
      }))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()
    expect(wrapper.text()).toContain("学生提交自讲")
    expect(wrapper.text()).toContain("模型调用（success）")
    expect(fetchMock).toHaveBeenCalledTimes(1)

    const detail = wrapper.findAll("details.event-detail")[1]
    await detail.trigger("toggle")
    await flushPromises()

    expect(fetchMock).toHaveBeenLastCalledWith("/api/sessions/42/events/3", expect.any(Object))
    expect(wrapper.text()).toContain("model.requested")
  })

  it("切换 Trace 时读取指定 run，并显示后端返回的因果树", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({
        sessionId: 42,
        runs: [{ runId: "run-1", startedAt: "2026-08-20T10:00:00Z", steps: [] }],
      }))
      .mockResolvedValueOnce(response({
        sessionId: 42,
        runId: "run-1",
        roots: [{ seq: 1, eventType: "user.message", children: [{ seq: 3, eventType: "model.requested", children: [] }] }],
      }))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()
    await wrapper.get(".view-switch button:nth-child(3)").trigger("click")
    await flushPromises()

    expect(fetchMock).toHaveBeenLastCalledWith("/api/sessions/42/trace?run_id=run-1", expect.any(Object))
    expect(wrapper.text()).toContain("#1 user.message")
    expect(wrapper.text()).toContain("#3 model.requested")
  })

  it("切换 Surface 时读取模型可见消息和上下文", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({
        sessionId: 42,
        runs: [{ runId: "run-1", startedAt: "2026-08-20T10:00:00Z", steps: [] }],
      }))
      .mockResolvedValueOnce(response({
        sessionId: 42,
        asOfSeq: 5,
        messages: [{ seq: 1, role: "user", content: "学生的完整回答" }],
        contexts: [{
          seq: 3,
          kind: "question",
          source: "question:7",
          content: { questionContent: "计算 1 + 1。" },
        }],
      }))
    vi.stubGlobal("fetch", fetchMock)

    const wrapper = await mountView()
    await wrapper.findAll(".view-switch button")[0].trigger("click")
    await flushPromises()

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/sessions/42/surface",
      expect.any(Object),
    )
    expect(wrapper.text()).toContain("学生的完整回答")
    expect(wrapper.text()).toContain("question")
    expect(wrapper.text()).toContain("#5")
  })
})
