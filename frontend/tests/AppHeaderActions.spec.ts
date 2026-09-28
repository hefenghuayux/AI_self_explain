import { flushPromises, mount, type VueWrapper } from "@vue/test-utils"
import ElementPlus from "element-plus"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import * as authApi from "../src/api/auth"
import * as questionApi from "../src/api/questions"
import * as sessionApi from "../src/api/sessions"
import App from "../src/App.vue"
import { login } from "../src/stores/auth"
import type { User, UserRole } from "../src/types/auth"
import type { Session } from "../src/types/session"
import SessionView from "../src/views/SessionView.vue"

vi.mock("../src/api/auth", () => ({
  fetchCurrentUser: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  register: vi.fn(),
}))

vi.mock("../src/api/questions", () => ({ fetchQuestion: vi.fn() }))

vi.mock("../src/api/sessions", () => ({
  SessionApiError: class SessionApiError extends Error {},
  askDoubt: vi.fn(),
  continueExplaining: vi.fn(),
  createSession: vi.fn(),
  fetchLearningTimeline: vi.fn(),
  fetchSession: vi.fn(),
  requestSupport: vi.fn(),
  submitAppeal: vi.fn(),
  submitGuidedAnswers: vi.fn(),
  submitInitialChoice: vi.fn(),
  submitMasteryCheckAnswers: vi.fn(),
  submitSolutionUnderstanding: vi.fn(),
  submitTextAttempt: vi.fn(),
}))

const loginRequest = vi.mocked(authApi.login)
const fetchLearningTimeline = vi.mocked(sessionApi.fetchLearningTimeline)
const fetchSession = vi.mocked(sessionApi.fetchSession)
const fetchQuestion = vi.mocked(questionApi.fetchQuestion)

function createSession(): Session {
  return {
    id: 12,
    questionId: 3,
    status: "IN_PROGRESS",
    flowStage: "WAIT_STUDENT_ACTION",
    round: 1,
    supportCountRound: 0,
    supportCountTotal: 0,
    noProgressCount: 0,
    noProgressHelpRequestCount: 0,
    solutionExposed: false,
    completionType: null,
    currentDraft: "",
    version: 1,
    initialChoice: null,
    needHumanReason: null,
    latestEvaluation: null,
    latestSupport: null,
    teachingGeneration: null,
    masteryCheck: null,
  }
}

// SessionView 通过 Teleport 把页面操作渲染进 App.vue 顶栏容器，而 Teleport 按选择器在
// document 中查找目标，因此本文件必须把 App 挂载到真实 DOM 容器，不能挂载到游离节点。
let container: HTMLDivElement
let wrapper: VueWrapper | undefined

async function mountApp(role: UserRole) {
  const user: User = { id: 1, username: "tester", fullName: "测试用户", role }
  loginRequest.mockResolvedValue({ token: "test-token", expiresAt: "2026-07-20T00:00:00Z", user })
  await login("tester", "secret6", false)

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { template: "<div />" } },
      { path: "/sessions/:sessionId/logs", component: { template: "<div />" } },
      { path: "/sessions/:sessionId", component: SessionView },
    ],
  })
  await router.push("/sessions/12")
  await router.isReady()
  wrapper = mount(App, { attachTo: container, global: { plugins: [ElementPlus, router] } })
  await flushPromises()
  return wrapper
}

describe("App header session actions", () => {
  beforeEach(() => {
    container = document.createElement("div")
    document.body.appendChild(container)
    vi.resetAllMocks()
    localStorage.clear()
    fetchLearningTimeline.mockResolvedValue([])
    fetchSession.mockResolvedValue(createSession())
    fetchQuestion.mockResolvedValue({
      id: 3,
      evaluationMode: "FULL_RUBRIC",
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

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
    container.remove()
  })

  it("renders the session actions in the top bar next to the logout button", async () => {
    const wrapper = await mountApp("TEACHER")
    const accountArea = wrapper.get(".account-area")

    expect(accountArea.text()).toContain("重新自讲")
    expect(accountArea.text()).toContain("查看运行日志")
    expect(accountArea.text()).toContain("返回题目列表")
    expect(accountArea.text()).toContain("退出登录")
    expect(accountArea.text().indexOf("返回题目列表")).toBeLessThan(accountArea.text().indexOf("退出登录"))

    const sessionPage = wrapper.get("main.session-page")
    expect(sessionPage.text()).not.toContain("重新自讲")
    expect(sessionPage.find("h1").exists()).toBe(false)
    expect(sessionPage.text()).not.toContain("用自己的语言讲清思路")
  })

  it("hides the run log entry from students", async () => {
    const wrapper = await mountApp("STUDENT")
    const accountArea = wrapper.get(".account-area")

    expect(accountArea.text()).toContain("重新自讲")
    expect(accountArea.text()).toContain("返回题目列表")
    expect(accountArea.text()).not.toContain("查看运行日志")
  })
})
