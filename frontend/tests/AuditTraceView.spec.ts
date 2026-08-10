import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, describe, expect, it, vi } from "vitest"

import AuditTraceView from "../src/views/AuditTraceView.vue"

describe("AuditTraceView", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows the business chain by default and groups full audit events by requestId", async () => {
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
              operation: { name: "SELECT_INITIAL_CHOICE" },
              result: { status: "SUCCESS", durationMs: null, errorType: null, errorMessage: null },
              data: {},
              references: {},
              privacy: { redactedFields: [] },
            },
            {
              schemaVersion: "2.0",
              eventId: "evaluation-1",
              sequence: 3,
              occurredAt: "2026-08-10T10:02:00Z",
              eventName: "ai.output.validated",
              severity: "INFO",
              source: {},
              correlation: { sessionId: 42, requestId: "request-1" },
              operation: { name: "VALIDATE_AI_EVALUATION" },
              result: { status: "SUCCESS", durationMs: 100, errorType: null, errorMessage: null },
              data: {},
              references: {},
              privacy: { redactedFields: [] },
            },
            {
              schemaVersion: "2.0",
              eventId: "external-call-1",
              sequence: 4,
              occurredAt: "2026-08-10T10:02:00Z",
              eventName: "ai.call.completed",
              severity: "INFO",
              source: {},
              correlation: { sessionId: 42, requestId: "request-1" },
              operation: { name: "AI_EVALUATION" },
              result: { status: "SUCCESS", durationMs: 100, errorType: null, errorMessage: null },
              data: {},
              references: {},
              privacy: { redactedFields: [] },
            },
            {
              schemaVersion: "2.0",
              eventId: "attempt-1",
              sequence: 5,
              occurredAt: "2026-08-10T10:01:00Z",
              eventName: "student.input.confirmed",
              severity: "INFO",
              source: {},
              correlation: { sessionId: 42, requestId: "request-1" },
              operation: { name: "CAPTURE_INPUT" },
              result: { status: "SUCCESS", durationMs: null, errorType: null, errorMessage: null },
              data: {},
              references: {},
              privacy: { redactedFields: [] },
            },
            {
              schemaVersion: "2.0",
              eventId: "submission-1",
              sequence: 6,
              occurredAt: "2026-08-10T10:01:00Z",
              eventName: "student.input.submitted",
              severity: "INFO",
              source: {},
              correlation: { sessionId: 42, requestId: "request-1" },
              operation: { name: "SELF_EXPLANATION" },
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
    expect(wrapper.text()).toContain("学生提交答案")
    expect(wrapper.text()).toContain("state.transitioned · SELECT_INITIAL_CHOICE")
    expect(wrapper.findAll(".trace-group")).toHaveLength(3)
    expect(wrapper.findAll(".related-events")).toHaveLength(2)
    expect(wrapper.findAll(".related-events")[1].text()).toContain("ai.call.completed")

    await wrapper.findAll(".view-switch button")[1].trigger("click")
    expect(wrapper.text()).toContain("requestId · request-1")
    expect(wrapper.findAll(".trace-group")).toHaveLength(2)

    await wrapper.find("select").setValue("session.created")
    expect(wrapper.findAll(".trace-group")).toHaveLength(1)
    expect(wrapper.text()).toContain("无 requestId（会话级事件）")
  })
})
