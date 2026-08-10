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
          schemaVersion: "2.0",
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
              schemaVersion: "2.0",
              eventId: "state-transition-1",
              sequence: 1,
              occurredAt: "2026-08-10T10:00:00Z",
              eventName: "session.created",
              severity: "INFO",
              source: {},
              correlation: { sessionId: 42, requestId: null },
              operation: {},
              result: { status: "SUCCESS", durationMs: null, errorType: null, errorMessage: null },
              data: {},
              references: {},
              privacy: { redactedFields: [] },
            },
            {
              schemaVersion: "2.0",
              eventId: "state-transition-2",
              sequence: 2,
              occurredAt: "2026-08-10T10:01:00Z",
              eventName: "state.transitioned",
              severity: "INFO",
              source: {},
              correlation: { sessionId: 42, requestId: "request-1" },
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

    expect(wrapper.text()).toContain("PAUSED")
    expect(wrapper.text()).toContain("事件数量")
    expect(wrapper.findAll("details")).toHaveLength(2)

    await wrapper.find("select").setValue("session.created")
    expect(wrapper.findAll("details")).toHaveLength(1)
  })
})
