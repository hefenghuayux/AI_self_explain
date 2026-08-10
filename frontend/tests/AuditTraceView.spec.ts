import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, describe, expect, it, vi } from "vitest"

import AuditTraceView from "../src/views/AuditTraceView.vue"

describe("AuditTraceView", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows summary and filtered JSON events", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          schemaVersion: "1.0",
          sessionId: 42,
          generatedAt: "2026-08-10T10:00:00Z",
          summary: {
            status: "PAUSED",
            flowStage: "CAPTURING_INPUT",
            round: 1,
            eventCount: 2,
            errorCount: 0,
            externalCallCount: 0,
          },
          events: [
            {
              schemaVersion: "1.0",
              eventId: "state-transition-1",
              sequence: 1,
              occurredAt: "2026-08-10T10:00:00Z",
              eventName: "session.created",
              severity: "INFO",
              source: {},
              correlation: { sessionId: 42, requestId: null, traceId: "session-42", spanId: "state-transition-1", parentSpanId: null },
              operation: {},
              result: { status: "SUCCESS", durationMs: null, errorType: null, errorMessage: null },
              data: {},
              references: {},
              privacy: { redactedFields: [] },
            },
            {
              schemaVersion: "1.0",
              eventId: "state-transition-2",
              sequence: 2,
              occurredAt: "2026-08-10T10:01:00Z",
              eventName: "state.transitioned",
              severity: "INFO",
              source: {},
              correlation: { sessionId: 42, requestId: "request-1", traceId: "request-1", spanId: "state-transition-2", parentSpanId: null },
              operation: {},
              result: { status: "SUCCESS", durationMs: null, errorType: null, errorMessage: null },
              data: {},
              references: {},
              privacy: { redactedFields: [] },
            },
          ],
        }),
      }),
    )
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/sessions/:sessionId", component: { template: "<div />" } },
        { path: "/sessions/:sessionId/audit", component: AuditTraceView },
      ],
    })
    await router.push("/sessions/42/audit")
    await router.isReady()
    const wrapper = mount(AuditTraceView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain("已暂停")
    expect(wrapper.text()).toContain("事件数量")
    expect(wrapper.text()).toContain("会话已创建")
    expect(wrapper.text()).toContain("字段解释")
    expect(wrapper.text()).toContain("事件编号")
    expect(wrapper.text()).toContain("这条事件的唯一编号")
    expect(wrapper.findAll(".event-card")).toHaveLength(2)

    await wrapper.find("select").setValue("session.created")
    expect(wrapper.findAll(".event-card")).toHaveLength(1)
  })
})
