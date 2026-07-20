import { flushPromises, mount } from "@vue/test-utils"
import ElementPlus from "element-plus"
import { createMemoryHistory, createRouter } from "vue-router"
import { beforeEach, describe, expect, it, vi } from "vitest"

import * as sessionApi from "../src/api/sessions"
import SessionView from "../src/views/SessionView.vue"
import type { Session } from "../src/types/session"

vi.mock("../src/api/sessions", () => ({
  fetchSession: vi.fn(),
  submitInitialChoice: vi.fn(),
  submitTextAttempt: vi.fn(),
}))

const fetchSession = vi.mocked(sessionApi.fetchSession)
const submitInitialChoice = vi.mocked(sessionApi.submitInitialChoice)
const submitTextAttempt = vi.mocked(sessionApi.submitTextAttempt)

function createSession(overrides: Partial<Session> = {}): Session {
  return {
    id: 12,
    questionId: 3,
    status: "IN_PROGRESS",
    flowStage: "WAIT_INITIAL_CHOICE",
    round: 1,
    version: 1,
    initialChoice: null,
    ...overrides,
  }
}

async function mountSessionView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/sessions/:sessionId", component: SessionView },
      { path: "/questions/:questionId", component: { template: "<div />" } },
    ],
  })
  await router.push("/sessions/12")
  await router.isReady()
  const wrapper = mount(SessionView, { global: { plugins: [ElementPlus, router] } })
  await flushPromises()
  return wrapper
}

describe("SessionView", () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it("records the initial KNOW choice with the current session version", async () => {
    fetchSession.mockResolvedValue(createSession())
    submitInitialChoice.mockResolvedValue(
      createSession({ flowStage: "CAPTURING_INPUT", version: 2, initialChoice: "KNOW" }),
    )
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="initial-choice-know"]').trigger("click")
    await flushPromises()

    expect(submitInitialChoice).toHaveBeenCalledWith("12", "KNOW", 1)
    expect(wrapper.text()).toContain("请用自己的话讲解")
  })

  it("does not submit whitespace-only text", async () => {
    fetchSession.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT", initialChoice: "KNOW" }))
    const wrapper = await mountSessionView()

    await wrapper.get("textarea").setValue("   ")
    await wrapper.get('[data-testid="submit-text"]').trigger("click")
    await flushPromises()

    expect(submitTextAttempt).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain("请输入自讲内容后再确认提交")
  })

  it("submits confirmed text with the session version", async () => {
    fetchSession.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT", initialChoice: "KNOW" }))
    submitTextAttempt.mockResolvedValue(
      createSession({ flowStage: "AI_EVALUATING", version: 2, initialChoice: "KNOW" }),
    )
    const wrapper = await mountSessionView()

    await wrapper.get("textarea").setValue("我先说明计算过程。")
    await wrapper.get('[data-testid="submit-text"]').trigger("click")
    await flushPromises()

    expect(submitTextAttempt).toHaveBeenCalledWith("12", "我先说明计算过程。", 1)
    expect(wrapper.text()).toContain("自讲内容已保存")
  })
})
