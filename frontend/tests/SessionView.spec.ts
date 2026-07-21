import { flushPromises, mount } from "@vue/test-utils"
import ElementPlus from "element-plus"
import { createMemoryHistory, createRouter } from "vue-router"
import { beforeEach, describe, expect, it, vi } from "vitest"

import * as sessionApi from "../src/api/sessions"
import * as questionApi from "../src/api/questions"
import SessionView from "../src/views/SessionView.vue"
import type { Session } from "../src/types/session"

vi.mock("../src/api/questions", () => ({
  fetchQuestion: vi.fn(),
}))

vi.mock("../src/api/sessions", () => ({
  continueExplaining: vi.fn(),
  fetchSession: vi.fn(),
  requestSupport: vi.fn(),
  retryEvaluation: vi.fn(),
  submitAppeal: vi.fn(),
  submitInitialChoice: vi.fn(),
  submitSolutionUnderstanding: vi.fn(),
  submitTextAttempt: vi.fn(),
}))

const continueExplaining = vi.mocked(sessionApi.continueExplaining)
const fetchSession = vi.mocked(sessionApi.fetchSession)
const fetchQuestion = vi.mocked(questionApi.fetchQuestion)
const requestSupport = vi.mocked(sessionApi.requestSupport)
const retryEvaluation = vi.mocked(sessionApi.retryEvaluation)
const submitAppeal = vi.mocked(sessionApi.submitAppeal)
const submitInitialChoice = vi.mocked(sessionApi.submitInitialChoice)
const submitSolutionUnderstanding = vi.mocked(sessionApi.submitSolutionUnderstanding)
const submitTextAttempt = vi.mocked(sessionApi.submitTextAttempt)

function createSession(overrides: Partial<Session> = {}): Session {
  return {
    id: 12,
    questionId: 3,
    status: "IN_PROGRESS",
    flowStage: "WAIT_INITIAL_CHOICE",
    round: 1,
    supportCountRound: 0,
    supportCountTotal: 0,
    noProgressCount: 0,
    solutionExposed: false,
    completionType: null,
    coveredPointsCurrentRound: [],
    coveredPointsAll: [],
    version: 1,
    initialChoice: null,
    needHumanReason: null,
    latestEvaluation: null,
    latestSupport: null,
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
    fetchQuestion.mockResolvedValue({
      id: 3,
      questionContent: "计算 1 + 1。",
      standardAnswer: "2",
      rubricPoints: ["正确计算加法"],
      commonErrors: ["把结果写成 3"],
      alternativeSolutions: ["使用实物计数"],
      layeredHints: ["先数一数"],
      fullSolution: "1 加 1 等于 2。",
      archivedAt: null,
      createdAt: "2026-07-20T00:00:00Z",
      updatedAt: "2026-07-20T00:00:00Z",
    })
  })

  it("keeps the associated question visible throughout the self-explanation session", async () => {
    fetchSession.mockResolvedValue(createSession())
    const wrapper = await mountSessionView()

    expect(fetchQuestion).toHaveBeenCalledWith("3")
    expect(wrapper.get('[data-testid="question-content"]').text()).toBe("计算 1 + 1。")
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
      createSession({
        flowStage: "WAIT_STUDENT_ACTION",
        version: 2,
        initialChoice: "KNOW",
        latestEvaluation: {
          id: 3,
          correctness: "CORRECT",
          completeness: "INCOMPLETE",
          coveredPoints: ["正确计算加法"],
          missingPoints: ["得出结果 2"],
          errorEvidence: [],
          feedback: "你已经说明了加法过程，请补充结果。",
          confidence: 1,
          nextAction: "ASK_FOCUSED_QUESTION",
          needHumanReason: null,
          promptVersion: "test-v1",
          modelProvider: "test-ai",
          modelName: "test-ai-model",
          createdAt: "2026-07-20T00:00:00Z",
        },
      }),
    )
    const wrapper = await mountSessionView()

    await wrapper.get("textarea").setValue("我先说明计算过程。")
    await wrapper.get('[data-testid="submit-text"]').trigger("click")
    await flushPromises()

    expect(submitTextAttempt).toHaveBeenCalledWith("12", "我先说明计算过程。", 1)
    expect(wrapper.get('[data-testid="ai-feedback"]').text()).toContain("请补充结果")
  })

  it("retries an evaluation without requiring the student to re-enter text", async () => {
    fetchSession.mockResolvedValue(
      createSession({ flowStage: "CONFIRMING_TEXT", version: 4, initialChoice: "KNOW" }),
    )
    retryEvaluation.mockResolvedValue(
      createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 6, initialChoice: "KNOW" }),
    )
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="retry-evaluation"]').trigger("click")
    await flushPromises()

    expect(retryEvaluation).toHaveBeenCalledWith("12", 4)
  })

  it("allows the student to continue or request another support", async () => {
    fetchSession.mockResolvedValue(
      createSession({
        flowStage: "WAIT_STUDENT_ACTION",
        version: 4,
        latestSupport: {
          id: 8,
          supportType: "GIVE_HINT",
          round: 1,
          status: "VALID",
          content: "请先重新检查加法结果。",
          createdAt: "2026-07-20T00:00:00Z",
        },
      }),
    )
    requestSupport.mockResolvedValue(
      createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 5 }),
    )
    const wrapper = await mountSessionView()

    expect(wrapper.get('[data-testid="support-content"]').text()).toContain("重新检查")
    await wrapper.get('[data-testid="request-support"]').trigger("click")
    await flushPromises()

    expect(requestSupport).toHaveBeenCalledWith("12", 4)
    continueExplaining.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT", version: 6 }))
    await wrapper.get('[data-testid="continue-explaining"]').trigger("click")
    await flushPromises()

    expect(continueExplaining).toHaveBeenCalledWith("12", 5)
  })

  it("requires an appeal reason before submitting the appeal", async () => {
    fetchSession.mockResolvedValue(
      createSession({
        flowStage: "WAIT_STUDENT_ACTION",
        version: 4,
        latestEvaluation: {
          id: 3,
          correctness: "CORRECT",
          completeness: "INCOMPLETE",
          coveredPoints: ["正确计算加法"],
          missingPoints: ["得出结果 2"],
          errorEvidence: [],
          feedback: "请补充结果。",
          confidence: 1,
          nextAction: "ASK_FOCUSED_QUESTION",
          needHumanReason: null,
          promptVersion: "test-v1",
          modelProvider: "test-ai",
          modelName: "test-ai-model",
          createdAt: "2026-07-20T00:00:00Z",
        },
      }),
    )
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="submit-appeal"]').trigger("click")
    await flushPromises()

    expect(submitAppeal).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain("请填写不同意 AI 判断的理由")
  })

  it("starts the second round only after the first full solution is understood", async () => {
    fetchSession.mockResolvedValue(
      createSession({ flowStage: "SHOWING_FULL_SOLUTION", version: 7, solutionExposed: true }),
    )
    submitSolutionUnderstanding.mockResolvedValue(
      createSession({ flowStage: "CAPTURING_INPUT", round: 2, version: 8, solutionExposed: true }),
    )
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="understood-solution"]').trigger("click")
    await flushPromises()

    expect(submitSolutionUnderstanding).toHaveBeenCalledWith("12", true, 7)
    expect(wrapper.text()).toContain("请用自己的话讲解")
  })
})
