import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, describe, expect, it, vi } from "vitest"

import AuditTraceView from "../src/views/AuditTraceView.vue"

const aiEvent = {
  eventId: "external-call-1",
  sequence: 2,
  occurredAt: "2026-08-10T10:02:00Z",
  eventName: "ai.call.completed",
  severity: "INFO",
  correlation: { sessionId: 42, requestId: "request-1" },
  operation: { name: "AI_EVALUATION" },
  result: { status: "SUCCESS", durationMs: 100 },
  data: {
    requestSnapshot: {
      schemaVersion: "1.0",
      purpose: "AI_EVALUATION",
      promptVersion: "evaluation-v1",
      blocks: {
        systemInstructions: "评价规则",
        questionContext: { standardAnswer: "2" },
        sessionContext: { round: 1 },
        userInput: { confirmedText: "很长的学生输入" },
        retryContext: { validationErrors: [] },
      },
      transport: {
        model: "test-model",
        messages: [{ role: "user", content: "实际提示词" }],
        response_format: { type: "json_object" },
      },
      privacy: {
        containsStudentContent: true,
        containsAnswerMaterial: true,
        containsMemory: false,
      },
    },
  },
  references: { externalCallRecordId: 1 },
}

const sessionEvent = {
  eventId: "state-transition-1",
  sequence: 1,
  occurredAt: "2026-08-10T10:00:00Z",
  eventName: "session.created",
  severity: "INFO",
  correlation: { sessionId: 42 },
  operation: { name: "CREATE_SESSION" },
  result: { status: "SUCCESS" },
  data: {},
  references: {},
}

describe("AuditTraceView", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("uses backend business steps and keeps full audit grouped by requestId", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            schemaVersion: "3.0",
            producer: { service: "ai-self-explain-backend", version: "0.1.0" },
            sessionId: 42,
            generatedAt: "2026-08-10T10:00:00Z",
            summary: {
              status: "PAUSED",
              flowStage: "CAPTURING_INPUT",
              round: 1,
              eventCount: 2,
              errorCount: 0,
              externalCallCount: 1,
            },
            events: [sessionEvent, aiEvent],
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            sessionId: 42,
            generatedAt: "2026-08-10T10:00:00Z",
            steps: [
              {
                stepId: "session-state-transition-1",
                kind: "SESSION",
                title: "会话开始与输入方式",
                status: "SUCCESS",
                occurredAt: "2026-08-10T10:00:00Z",
                summary: "会话已创建。",
                eventIds: [sessionEvent.eventId],
                events: [sessionEvent],
              },
              {
                stepId: "ai-external-call-1",
                kind: "AI",
                title: "AI 评价与确定性规则",
                status: "WARNING",
                occurredAt: "2026-08-10T10:02:00Z",
                summary: "模型共调用 2 次，输出校验通过。",
                eventIds: [aiEvent.eventId],
                events: [aiEvent],
                requestId: "request-1",
                durationMs: 100,
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
    expect(wrapper.findAll(".trace-step")).toHaveLength(2)
    expect(wrapper.text()).toContain("AI 评价与确定性规则")
    expect(wrapper.text()).toContain("本次未注入记忆")
    expect(wrapper.text()).toContain("模型请求 1")
    expect(wrapper.text()).not.toContain("undefined")

    await wrapper.findAll(".view-switch button")[1].trigger("click")
    expect(wrapper.text()).toContain("requestId · request-1")
    expect(wrapper.findAll(".trace-group")).toHaveLength(2)
  })
})
