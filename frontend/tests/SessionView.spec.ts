import { flushPromises, mount } from "@vue/test-utils"
import ElementPlus from "element-plus"
import { createMemoryHistory, createRouter } from "vue-router"
import { beforeEach, describe, expect, it, vi } from "vitest"

import * as sessionApi from "../src/api/sessions"
import * as questionApi from "../src/api/questions"
import SessionView from "../src/views/SessionView.vue"
import type { Session } from "../src/types/session"

vi.mock("../src/api/questions", () => ({ fetchQuestion: vi.fn() }))
vi.mock("../src/api/sessions", () => ({
  askDoubt: vi.fn(),
  continueExplaining: vi.fn(),
  fetchLearningTimeline: vi.fn(),
  fetchSession: vi.fn(),
  requestSupport: vi.fn(),
  retryEvaluation: vi.fn(),
  submitAppeal: vi.fn(),
  submitGuidedAnswers: vi.fn(),
  submitInitialChoice: vi.fn(),
  submitSolutionUnderstanding: vi.fn(),
  submitTextAttempt: vi.fn(),
}))

const askDoubt = vi.mocked(sessionApi.askDoubt)
const continueExplaining = vi.mocked(sessionApi.continueExplaining)
const fetchLearningTimeline = vi.mocked(sessionApi.fetchLearningTimeline)
const fetchSession = vi.mocked(sessionApi.fetchSession)
const fetchQuestion = vi.mocked(questionApi.fetchQuestion)
const requestSupport = vi.mocked(sessionApi.requestSupport)
const submitGuidedAnswers = vi.mocked(sessionApi.submitGuidedAnswers)
const submitInitialChoice = vi.mocked(sessionApi.submitInitialChoice)
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
    noProgressHelpRequestCount: 0,
    solutionExposed: false,
    completionType: null,
    coveredPointsCurrentRound: [],
    coveredPointsAll: [],
    currentDraft: "",
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
    fetchLearningTimeline.mockResolvedValue([])
    fetchQuestion.mockResolvedValue({
      id: 3,
      questionContent: "计算 1 + 1。",
      standardAnswer: "2",
      rubricPoints: ["正确计算加法"],
      commonErrors: ["把结果写成 3"],
      alternativeSolutions: ["使用实物计数"],
      layeredHints: ["先数一数"],
      guidedQuestions: ["两个 1 合起来是多少？"],
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

  it("submits the initial draft when the student chooses to submit an explanation", async () => {
    fetchSession.mockResolvedValue(createSession())
    submitInitialChoice.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT", version: 2, initialChoice: "KNOW" }))
    submitTextAttempt.mockResolvedValue(createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 3, currentDraft: "1 加 1 等于 2。" }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="main-draft"]').setValue("1 加 1 等于 2。")
    await wrapper.get('[data-testid="submit-explanation"]').trigger("click")
    await flushPromises()

    expect(submitInitialChoice).toHaveBeenCalledWith("12", "KNOW", 1)
    expect(submitTextAttempt).toHaveBeenCalledWith("12", "1 加 1 等于 2。", 2)
  })

  it("reminds once before allowing an empty draft to request support", async () => {
    fetchSession.mockResolvedValue(createSession())
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="request-support"]').trigger("click")
    await flushPromises()
    expect(submitInitialChoice).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain("请先输入当前的题干理解")
  })

  it("sends the retained main draft when requesting guided support", async () => {
    fetchSession.mockResolvedValue(createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 4, currentDraft: "我知道有两个 1。" }))
    requestSupport.mockResolvedValue(createSession({ flowStage: "WAIT_GUIDED_ANSWERS", version: 5, currentDraft: "我知道有两个 1。" }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="main-draft"]').setValue("我知道有两个 1，并想继续计算。")
    await wrapper.get('[data-testid="request-support"]').trigger("click")
    await flushPromises()

    expect(requestSupport).toHaveBeenCalledWith("12", "我知道有两个 1，并想继续计算。", 4)
  })

  it("submits all guided answers without creating another support request", async () => {
    fetchSession.mockResolvedValue(createSession({
      flowStage: "WAIT_GUIDED_ANSWERS",
      version: 5,
      latestSupport: {
        id: 9,
        supportType: "GIVE_HINT",
        supportKind: "GUIDED_QUESTIONS",
        round: 1,
        status: "VALID",
        content: "请回答问题。",
        mainDraft: "我知道有两个 1。",
        doubtText: null,
        guidedQuestions: [
          { id: "q1", question: "第一个 1 表示什么？" },
          { id: "q2", question: "两个 1 合起来是多少？" },
        ],
        guidedAnswers: null,
        followUpContent: null,
        createdAt: "2026-07-20T00:00:00Z",
      },
    }))
    submitGuidedAnswers.mockResolvedValue(createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 6 }))
    const wrapper = await mountSessionView()

    const inputs = wrapper.findAll("textarea")
    await inputs[1].setValue("一个数量")
    await inputs[2].setValue("2")
    await wrapper.get('[data-testid="submit-guided-answers"]').trigger("click")
    await flushPromises()

    expect(submitGuidedAnswers).toHaveBeenCalledWith("12", [
      { questionId: "q1", answer: "一个数量" },
      { questionId: "q2", answer: "2" },
    ], 5)
    expect(askDoubt).not.toHaveBeenCalled()
    expect(continueExplaining).not.toHaveBeenCalled()
  })
})
