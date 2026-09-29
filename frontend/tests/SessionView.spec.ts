import { flushPromises, mount } from "@vue/test-utils"
import ElementPlus from "element-plus"
import { createMemoryHistory, createRouter } from "vue-router"
import { beforeEach, describe, expect, it, vi } from "vitest"

import * as sessionApi from "../src/api/sessions"
import * as sessionStepsApi from "../src/api/session-steps"
import * as questionApi from "../src/api/questions"
import VoiceRecorder from "../src/components/VoiceRecorder.vue"
import SessionView from "../src/views/SessionView.vue"
import type { Session } from "../src/types/session"

vi.mock("../src/api/questions", () => ({ fetchQuestion: vi.fn() }))
vi.mock("../src/api/sessions", () => ({
  SessionApiError: class SessionApiError extends Error {
    constructor(
      message: string,
      readonly status: number,
      readonly code?: string,
      readonly sessionId?: number,
    ) {
      super(message)
    }
  },
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
}))
vi.mock("../src/api/session-steps", () => ({
  activateStep: vi.fn(),
  fetchSessionSteps: vi.fn(),
  saveStepAndGoNext: vi.fn(),
  submitStepAttempt: vi.fn(),
}))

const askDoubt = vi.mocked(sessionApi.askDoubt)
const continueExplaining = vi.mocked(sessionApi.continueExplaining)
const createSessionRequest = vi.mocked(sessionApi.createSession)
const fetchLearningTimeline = vi.mocked(sessionApi.fetchLearningTimeline)
const fetchSession = vi.mocked(sessionApi.fetchSession)
const fetchQuestion = vi.mocked(questionApi.fetchQuestion)
const submitAppeal = vi.mocked(sessionApi.submitAppeal)
const submitGuidedAnswers = vi.mocked(sessionApi.submitGuidedAnswers)
const submitInitialChoice = vi.mocked(sessionApi.submitInitialChoice)
const submitMasteryCheckAnswers = vi.mocked(sessionApi.submitMasteryCheckAnswers)
const activateStep = vi.mocked(sessionStepsApi.activateStep)
const fetchSessionSteps = vi.mocked(sessionStepsApi.fetchSessionSteps)
const saveStepAndGoNext = vi.mocked(sessionStepsApi.saveStepAndGoNext)
const submitStepAttempt = vi.mocked(sessionStepsApi.submitStepAttempt)

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
    currentDraft: "",
    currentStepId: null,
    version: 1,
    initialChoice: null,
    needHumanReason: null,
    latestEvaluation: null,
    latestSupport: null,
    teachingGeneration: null,
    masteryCheck: null,
    ...overrides,
  }
}

function createSteps(overrides: Partial<{
  currentStepId: number | null
  version: number
  steps: Array<{
    id: number
    seq: number
    stepContent: string | null
    explainTranscript: string | null
    status: "DRAFT" | "SAVED" | "SUBMITTED"
    updatedAt: string
  }>
}> = {}) {
  return {
    round: 1,
    draftId: "draft-1",
    currentStepId: 101,
    version: 1,
    steps: [
      {
        id: 101,
        seq: 1,
        stepContent: "",
        explainTranscript: null,
        status: "DRAFT" as const,
        updatedAt: "2026-09-29T00:00:00Z",
      },
    ],
    ...overrides,
  }
}

async function mountSessionView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { template: "<div />" } },
      { path: "/sessions/:sessionId", component: SessionView },
    ],
  })
  await router.push("/sessions/12")
  await router.isReady()
  const wrapper = mount(SessionView, {
    // 页面操作按钮通过 Teleport 渲染到 App.vue 顶栏容器；本文件只挂载 SessionView，
    // 因此把 Teleport 替换为就地渲染的桩件，按钮仍可通过 wrapper 查询。
    global: { plugins: [ElementPlus, router], stubs: { teleport: true } },
  })
  await flushPromises()
  return wrapper
}

describe("SessionView", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    localStorage.clear()
    fetchLearningTimeline.mockResolvedValue([])
    fetchSessionSteps.mockResolvedValue(createSteps())
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

  it("keeps the associated question visible throughout the self-explanation session", async () => {
    fetchSession.mockResolvedValue(createSession())
    const wrapper = await mountSessionView()

    expect(fetchQuestion).toHaveBeenCalledWith("3")
    expect(wrapper.get('[data-testid="question-content"]').text()).toBe("计算 1 + 1。")
  })

  it("restarts self-explanation with a fresh session", async () => {
    fetchSession.mockResolvedValue(createSession())
    createSessionRequest.mockResolvedValue(createSession({ id: 18 }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="restart-self-explanation"]').trigger("click")
    await flushPromises()

    expect(createSessionRequest).toHaveBeenCalledWith("3", true)
  })

  it("keeps the self-explanation input available after human review is requested", async () => {
    fetchSession.mockResolvedValue(createSession({
      flowStage: "WAIT_STUDENT_ACTION",
      needHumanReason: "暂时无法可靠确认学生的计算依据。",
    }))

    const wrapper = await mountSessionView()

    expect(wrapper.text()).toContain("已申请人工复核，你可以继续自讲。")
    expect(wrapper.get('[data-testid="current-step-content"]').attributes("disabled")).toBeUndefined()
    expect(wrapper.get('[data-testid="submit-explanation"]')).toBeTruthy()
  })

  it("submits the initial draft when the student chooses to submit an explanation", async () => {
    fetchSession.mockResolvedValue(createSession())
    submitInitialChoice.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT", version: 2, initialChoice: "KNOW" }))
    submitStepAttempt.mockResolvedValue(createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 3, currentDraft: "1 加 1 等于 2。" }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="current-step-content"]').setValue("1 加 1 等于 2。")
    await wrapper.get('[data-testid="submit-explanation"]').trigger("click")
    await flushPromises()

    expect(submitInitialChoice).toHaveBeenCalledWith("12", "KNOW", 1)
    expect(submitStepAttempt).toHaveBeenCalledWith("12", 101, "1 加 1 等于 2。", 1)
  })

  it("keeps the step recording entries disabled while submitting an explanation", async () => {
    fetchSession.mockResolvedValue(createSession())
    submitInitialChoice.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT", version: 2, initialChoice: "KNOW" }))
    let resolveStepAttempt: (session: Session) => void = () => undefined
    submitStepAttempt.mockReturnValue(new Promise((resolve) => {
      resolveStepAttempt = resolve
    }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="current-step-content"]').setValue("1 加 1 等于 2。")
    const submitPromise = wrapper.get('[data-testid="submit-explanation"]').trigger("click")
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[data-testid="record-explain"]').attributes("disabled")).toBeDefined()
    expect(wrapper.get('[data-testid="record-step"]').attributes("disabled")).toBeDefined()

    resolveStepAttempt(createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 3 }))
    await submitPromise
    await flushPromises()
  })

  it("shows disabled step and explanation recording entries without voice guidance text", async () => {
    fetchSession.mockResolvedValue(createSession())
    const wrapper = await mountSessionView()

    expect(wrapper.get('[data-testid="record-explain"]').attributes("disabled")).toBeDefined()
    expect(wrapper.get('[data-testid="record-step"]').attributes("disabled")).toBeDefined()
    expect(wrapper.text()).not.toContain("使用语音自讲")
    expect(wrapper.text()).not.toContain("实时语音输入")
    expect(wrapper.text()).not.toContain("确认语音转写")
  })

  it("keeps the step controls in the same inline action row", async () => {
    fetchSession.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT" }))
    const wrapper = await mountSessionView()

    expect(wrapper.get(".self-explain-actions").find('[data-testid="record-explain"]').exists()).toBe(true)
    expect(wrapper.get(".self-explain-actions").find('[data-testid="record-step"]').exists()).toBe(true)
    expect(wrapper.get(".self-explain-actions").find('[data-testid="next-step"]').exists()).toBe(true)
  })

  it("sorts steps by sequence and initializes the current step content", async () => {
    fetchSession.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT", version: 3 }))
    fetchSessionSteps.mockResolvedValue(createSteps({
      currentStepId: 102,
      version: 3,
      steps: [
        {
          id: 102,
          seq: 2,
          stepContent: "第二步：得到结果。",
          explainTranscript: "这里说明第二步。",
          status: "DRAFT",
          updatedAt: "2026-09-29T00:00:02Z",
        },
        {
          id: 101,
          seq: 1,
          stepContent: "第一步：列出两个 1。",
          explainTranscript: null,
          status: "SAVED",
          updatedAt: "2026-09-29T00:00:01Z",
        },
      ],
    }))
    const wrapper = await mountSessionView()

    expect(wrapper.findAll('[data-testid^="step-item-"]').map((item) => item.attributes("data-testid"))).toEqual([
      "step-item-101",
      "step-item-102",
    ])
    expect((wrapper.get('[data-testid="current-step-content"]').element as HTMLTextAreaElement).value).toBe(
      "第二步：得到结果。",
    )
  })

  it("uses the server step content instead of a legacy self-explanation draft", async () => {
    fetchSession.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT" }))
    localStorage.setItem(
      "ai-self-explain:session:12:dialog-drafts",
      JSON.stringify({ selfExplain: "旧的整段自讲草稿" }),
    )
    fetchSessionSteps.mockResolvedValue(createSteps({
      steps: [{
        id: 101,
        seq: 1,
        stepContent: "服务端当前步骤",
        explainTranscript: null,
        status: "DRAFT",
        updatedAt: "2026-09-29T00:00:00Z",
      }],
    }))
    const wrapper = await mountSessionView()

    expect((wrapper.get('[data-testid="current-step-content"]').element as HTMLTextAreaElement).value).toBe(
      "服务端当前步骤",
    )
  })

  it("activates another step and saves the current step before switching", async () => {
    fetchSession.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT", version: 2 }))
    fetchSessionSteps.mockResolvedValue(createSteps({
      currentStepId: 101,
      version: 2,
      steps: [
        {
          id: 101,
          seq: 1,
          stepContent: "第一步",
          explainTranscript: null,
          status: "DRAFT",
          updatedAt: "2026-09-29T00:00:01Z",
        },
        {
          id: 102,
          seq: 2,
          stepContent: "第二步",
          explainTranscript: null,
          status: "SAVED",
          updatedAt: "2026-09-29T00:00:02Z",
        },
      ],
    }))
    activateStep.mockResolvedValue(createSteps({
      currentStepId: 102,
      version: 4,
      steps: [
        {
          id: 101,
          seq: 1,
          stepContent: "第一步已保存",
          explainTranscript: null,
          status: "SAVED",
          updatedAt: "2026-09-29T00:00:03Z",
        },
        {
          id: 102,
          seq: 2,
          stepContent: "第二步",
          explainTranscript: null,
          status: "DRAFT",
          updatedAt: "2026-09-29T00:00:04Z",
        },
      ],
    }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="current-step-content"]').setValue("第一步补充")
    await wrapper.get('[data-testid="step-item-102"]').trigger("click")
    await flushPromises()

    expect(activateStep).toHaveBeenCalledWith("12", 102, 101, "第一步补充", 2)
    expect((wrapper.get('[data-testid="current-step-content"]').element as HTMLTextAreaElement).value).toBe(
      "第二步",
    )
  })

  it("toggles the current step explanation without calling the activation API", async () => {
    fetchSession.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT" }))
    fetchSessionSteps.mockResolvedValue(createSteps({
      steps: [{
        id: 101,
        seq: 1,
        stepContent: "第一步",
        explainTranscript: "这里是第一步讲解。",
        status: "SAVED",
        updatedAt: "2026-09-29T00:00:00Z",
      }],
    }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="step-item-101"]').trigger("click")

    expect(activateStep).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="step-item-101"]').text()).toContain("这里是第一步讲解。")
  })

  it("rejects submitting or advancing an empty step", async () => {
    fetchSession.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT" }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="submit-explanation"]').trigger("click")
    await flushPromises()
    expect(submitStepAttempt).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain("当前步骤和讲解不能同时为空")

    await wrapper.get('[data-testid="next-step"]').trigger("click")
    await flushPromises()
    expect(saveStepAndGoNext).not.toHaveBeenCalled()
  })

  it("allows advancing when only step content is present", async () => {
    fetchSession.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT" }))
    saveStepAndGoNext.mockResolvedValue(createSteps({ currentStepId: 102, version: 2, steps: [
      {
        id: 101,
        seq: 1,
        stepContent: "第一步",
        explainTranscript: null,
        status: "SAVED",
        updatedAt: "2026-09-29T00:00:00Z",
      },
      {
        id: 102,
        seq: 2,
        stepContent: "",
        explainTranscript: null,
        status: "DRAFT",
        updatedAt: "2026-09-29T00:00:01Z",
      },
    ] }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="current-step-content"]').setValue("第一步")
    await wrapper.get('[data-testid="next-step"]').trigger("click")
    await flushPromises()

    expect(saveStepAndGoNext).toHaveBeenCalledWith("12", 101, "第一步", 1)
  })

  it("allows advancing when only an explanation transcript is present", async () => {
    fetchSession.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT" }))
    fetchSessionSteps.mockResolvedValue(createSteps({
      steps: [{
        id: 101,
        seq: 1,
        stepContent: "",
        explainTranscript: "我通过数一数得到结果。",
        status: "SAVED",
        updatedAt: "2026-09-29T00:00:00Z",
      }],
    }))
    saveStepAndGoNext.mockResolvedValue(createSteps({ currentStepId: 102, version: 2 }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="next-step"]').trigger("click")
    await flushPromises()

    expect(saveStepAndGoNext).toHaveBeenCalledWith("12", 101, "", 1)
  })

  it("applies the next-step response and its version to later submissions", async () => {
    fetchSession.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT" }))
    saveStepAndGoNext.mockResolvedValue(createSteps({
      currentStepId: 102,
      version: 6,
      steps: [
        {
          id: 101,
          seq: 1,
          stepContent: "第一步",
          explainTranscript: null,
          status: "SAVED",
          updatedAt: "2026-09-29T00:00:00Z",
        },
        {
          id: 102,
          seq: 2,
          stepContent: "第二步",
          explainTranscript: null,
          status: "DRAFT",
          updatedAt: "2026-09-29T00:00:01Z",
        },
      ],
    }))
    submitStepAttempt.mockResolvedValue(createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 7 }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="current-step-content"]').setValue("第一步")
    await wrapper.get('[data-testid="next-step"]').trigger("click")
    await flushPromises()
    await wrapper.get('[data-testid="submit-explanation"]').trigger("click")
    await flushPromises()

    expect(submitStepAttempt).toHaveBeenCalledWith("12", 102, "第二步", 6)
  })

  it("gives every guided question its own recording and submit controls", async () => {
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
    submitGuidedAnswers.mockResolvedValue(createSession({ flowStage: "WAIT_GUIDED_ANSWERS", version: 6 }))
    const wrapper = await mountSessionView()

    const guidedRecorders = wrapper.findAllComponents(VoiceRecorder).filter(
      (recorder) => recorder.props("target") === "GUIDED_ANSWER",
    )
    expect(guidedRecorders.map((recorder) => recorder.props("targetId"))).toEqual(["q1", "q2"])
    expect(guidedRecorders.every((recorder) => recorder.props("inline") === true)).toBe(true)
    guidedRecorders[0].vm.$emit("finalTranscript", "一个数量")
    await flushPromises()
    expect((wrapper.get('[data-testid="guided-answer-q1"]').element as HTMLTextAreaElement).value).toBe(
      "一个数量",
    )
    expect(wrapper.find('[data-testid="submit-guided-answer-q2"]').exists()).toBe(true)

    await wrapper.get('[data-testid="submit-guided-answer-q1"]').trigger("click")
    await flushPromises()

    expect(submitGuidedAnswers).toHaveBeenCalledWith(
      "12",
      [{ questionId: "q1", answer: "一个数量" }],
      5,
      undefined,
    )
    expect(askDoubt).not.toHaveBeenCalled()
    expect(continueExplaining).not.toHaveBeenCalled()
  })

  it("allows doubt and appeal submissions while evaluation questions are pending", async () => {
    const pendingQuestionSession = createSession({
      flowStage: "WAIT_GUIDED_ANSWERS",
      version: 5,
      latestEvaluation: {
        id: 7,
        correctness: "WRONG",
        completeness: "INCOMPLETE",
        promptVersion: "v1",
        modelProvider: "test",
        modelName: "test",
        createdAt: "2026-07-20T00:00:00Z",
      },
      latestSupport: {
        id: 9,
        supportType: "CORRECT_AND_ASK",
        supportKind: "GUIDED_QUESTIONS",
        round: 1,
        status: "VALID",
        content: "请回答问题。",
        mainDraft: "我知道有两个 1。",
        doubtText: null,
        guidedQuestions: [{ id: "q1", question: "两个 1 合起来是多少？" }],
        guidedAnswers: null,
        followUpContent: null,
        createdAt: "2026-07-20T00:00:00Z",
      },
    })
    fetchSession.mockResolvedValue(pendingQuestionSession)
    askDoubt.mockResolvedValue(createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 6 }))
    const wrapper = await mountSessionView()

    expect(wrapper.get('[data-testid="submit-doubt"]').attributes("disabled")).toBeUndefined()
    expect(wrapper.get('[data-testid="submit-appeal"]').attributes("disabled")).toBeUndefined()

    await wrapper.get('[data-testid="doubt-draft"]').setValue("为什么要重新计算？")
    await wrapper.get('[data-testid="submit-doubt"]').trigger("click")
    await flushPromises()

    expect(askDoubt).toHaveBeenCalledWith("12", "", "为什么要重新计算？", 5, undefined)
  })

  it("allows an appeal for a pending help question without an evaluation", async () => {
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
        guidedQuestions: [{ id: "q1", question: "两个 1 合起来是多少？" }],
        guidedAnswers: null,
        followUpContent: null,
        createdAt: "2026-07-20T00:00:00Z",
      },
    }))
    submitAppeal.mockResolvedValue(createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 6 }))
    const wrapper = await mountSessionView()

    expect(wrapper.get('[data-testid="submit-appeal"]').attributes("disabled")).toBeUndefined()
    await wrapper.get('[data-testid="appeal-draft"]').setValue("这个提示没有回答我的疑问。")
    await wrapper.get('[data-testid="submit-appeal"]').trigger("click")
    await flushPromises()

    expect(submitAppeal).toHaveBeenCalledWith("12", "这个提示没有回答我的疑问。", 5, undefined)
  })

  it("writes doubt and appeal transcripts into their own editable inputs", async () => {
    fetchSession.mockResolvedValue(createSession({
      flowStage: "WAIT_STUDENT_ACTION",
      latestEvaluation: {
        id: 7,
        correctness: "WRONG",
        completeness: "INCOMPLETE",
        promptVersion: "v1",
        modelProvider: "test",
        modelName: "test",
        createdAt: "2026-07-20T00:00:00Z",
      },
    }))
    const wrapper = await mountSessionView()
    const recorders = wrapper.findAllComponents(VoiceRecorder)
    const doubtRecorder = recorders.find((recorder) => recorder.props("target") === "DOUBT")
    const appealRecorder = recorders.find((recorder) => recorder.props("target") === "APPEAL")

    doubtRecorder?.vm.$emit("finalTranscript", "这里为什么要相加？")
    appealRecorder?.vm.$emit("finalTranscript", "我认为这一步没有错。")
    await flushPromises()

    expect((wrapper.get('[data-testid="doubt-draft"]').element as HTMLTextAreaElement).value).toBe(
      "这里为什么要相加？",
    )
    expect((wrapper.get('[data-testid="appeal-draft"]').element as HTMLTextAreaElement).value).toBe(
      "我认为这一步没有错。",
    )
  })

  it("uses the original doubt action after voice transcription", async () => {
    fetchSession
      .mockResolvedValueOnce(createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 7 }))
      .mockResolvedValueOnce(createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 8 }))
    askDoubt.mockResolvedValue(createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 9 }))
    const wrapper = await mountSessionView()

    expect(wrapper.findAllComponents(VoiceRecorder).map((recorder) => recorder.props("target"))).toEqual([
      "DOUBT",
    ])
    wrapper.findComponent(VoiceRecorder).vm.$emit("completed", 16)
    await flushPromises()
    await wrapper.get('[data-testid="doubt-draft"]').setValue("修改后的疑问")
    await wrapper.get('[data-testid="submit-doubt"]').trigger("click")
    await flushPromises()

    expect(askDoubt).toHaveBeenCalledWith("12", "", "修改后的疑问", 8, 16)
  })

  it("can reload the current session after an error", async () => {
    fetchSession
      .mockRejectedValueOnce(new Error("会话加载失败"))
      .mockResolvedValueOnce(createSession())
    const wrapper = await mountSessionView()

    expect(wrapper.text()).toContain("会话加载失败")
    await wrapper.get('[data-testid="continue-session"]').trigger("click")
    await flushPromises()

    expect(wrapper.get('[data-testid="question-content"]').text()).toBe("计算 1 + 1。")
  })

  it("reloads the persisted human-review state after teaching generation fails", async () => {
    fetchSession
      .mockResolvedValueOnce(createSession({ flowStage: "CAPTURING_INPUT", version: 2 }))
      .mockResolvedValueOnce(createSession({
        status: "IN_PROGRESS",
        flowStage: "WAIT_STUDENT_ACTION",
        version: 4,
        needHumanReason: "教学生成失败，会话已进入人工处理",
      }))
    submitStepAttempt.mockRejectedValue(
      new sessionApi.SessionApiError(
        "会话操作失败：教学生成失败，会话已进入人工处理",
        502,
        "TEACHING_GENERATION_FAILED",
        12,
      ),
    )
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="current-step-content"]').setValue("我先说明当前思路。")
    await wrapper.get('[data-testid="submit-explanation"]').trigger("click")
    await flushPromises()

    expect(fetchSession).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain("教学生成失败，会话已进入人工处理")
    expect(wrapper.text()).toContain("已申请人工复核，你可以继续自讲。")
  })

  it("renders student submissions and AI replies in the self-explanation record", async () => {
    fetchSession.mockResolvedValue(createSession())
    fetchLearningTimeline.mockResolvedValue([
      {
        id: "submission-1",
        eventType: "SUBMISSION",
        speaker: "STUDENT",
        submissionType: "SELF_EXPLANATION",
        content: "1 加 1 等于 2。",
        correctness: null,
        completeness: null,
        action: null,
        createdAt: "2026-07-20T00:00:00Z",
      },
      {
        id: "evaluation-1",
        eventType: "EVALUATION",
        speaker: "AI",
        submissionType: null,
        content: "还需要说明为什么是 2。",
        correctness: "CORRECT",
        completeness: "INCOMPLETE",
        action: "ASK_FOCUSED_QUESTION",
        createdAt: "2026-07-20T00:00:01Z",
      },
    ])
    const wrapper = await mountSessionView()

    expect(wrapper.text()).toContain("历史记录")
    expect(wrapper.text()).toContain("学生")
    expect(wrapper.text()).toContain("AI")
    const contents = wrapper.findAll('[data-testid="timeline-content"]').map((item) => item.text())
    expect(contents).toEqual(["1 加 1 等于 2。", "还需要说明为什么是 2。"])
    expect(wrapper.text()).not.toContain("按时间查看")
    expect(wrapper.text()).not.toContain("正确性")
    expect(wrapper.text()).not.toContain("完整性")
  })

  it("shows compact progress and feedback before the self-explanation actions", async () => {
    fetchSession.mockResolvedValue(createSession({
      flowStage: "WAIT_STUDENT_ACTION",
      latestEvaluation: {
        id: 4,
        correctness: "WRONG",
        completeness: "INCOMPLETE",
        promptVersion: "test",
        modelProvider: "test",
        modelName: "test",
        createdAt: "2026-07-20T00:00:00Z",
      },
      latestSupport: {
        id: 5,
        supportType: "GIVE_CORRECTION",
        supportKind: "EVALUATION",
        round: 1,
        status: "VALID",
        content: "请重新检查两个数相加的结果。",
        mainDraft: "1 加 1 等于 3。",
        doubtText: null,
        guidedQuestions: null,
        guidedAnswers: null,
        followUpContent: null,
        createdAt: "2026-07-20T00:00:00Z",
      },
    }))
    const wrapper = await mountSessionView()

    expect(wrapper.text()).toContain("最新反馈")
    expect(wrapper.text()).toContain("下一步：请重新检查两个数相加的结果。")
    expect(wrapper.find('[data-testid="request-support"]').exists()).toBe(false)
    expect(wrapper.get(".self-explain-actions").get('[data-testid="submit-explanation"]')).toBeTruthy()
    expect(wrapper.get(".self-explain-actions").find('[data-testid="record-explain"]').exists()).toBe(true)
    expect(wrapper.get(".self-explain-actions").find('[data-testid="record-step"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="dialog-segmented"]').text()).not.toContain("AI说错了")
    expect(wrapper.html().indexOf("最新反馈")).toBeLessThan(
      wrapper.html().indexOf('data-testid="dialog-segmented"'),
    )
    // 评价响应已不再返回 errorEvidence，反馈区不提供评价依据展开入口。
    expect(wrapper.find('[aria-controls="feedback-details"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain("查看评价依据")
    expect(wrapper.text()).not.toContain("先看结论")
    expect(wrapper.find(".evaluation-results").exists()).toBe(false)
    expect(wrapper.text()).not.toContain("正确性")
    expect(wrapper.text()).not.toContain("完整性")
  })

  it("shows the integrated guidance heading without a description line", async () => {
    fetchSession.mockResolvedValue(createSession({
      flowStage: "WAIT_STUDENT_ACTION",
      latestSupport: {
        id: 6,
        supportType: "GIVE_HINT",
        supportKind: "EVALUATION",
        round: 1,
        status: "VALID",
        content: "先看这一步。",
        mainDraft: "1 加 1 等于 3。",
        doubtText: null,
        guidedQuestions: null,
        guidedAnswers: null,
        followUpContent: "结合两个子问题的答案继续完成推理。",
        createdAt: "2026-07-20T00:00:00Z",
      },
    }))
    const wrapper = await mountSessionView()

    expect(wrapper.text()).toContain("整合引导")
    expect(wrapper.text()).not.toContain("结合子问题答案，继续完成整道题的推理。")
    expect(wrapper.text()).toContain("下一步：结合两个子问题的答案继续完成推理。")
  })

  it("restores saved drafts for each segmented input block", async () => {
    fetchSession.mockResolvedValue(createSession({
      flowStage: "WAIT_GUIDED_ANSWERS",
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
        ],
        guidedAnswers: null,
        followUpContent: null,
        createdAt: "2026-07-20T00:00:00Z",
      },
    }))
    localStorage.setItem(
      "ai-self-explain:session:12:dialog-drafts",
      JSON.stringify({
        guidedAnswers: { q1: "上次的答案" },
        masteryCheck: { mc1: "上次的核验回答" },
        doubt: "我的疑问",
        appeal: "我不同意",
      }),
    )
    const wrapper = await mountSessionView()

    expect(wrapper.find('[data-testid="current-step-content"]').exists()).toBe(false)
    expect((wrapper.get('[data-testid="guided-answer-q1"]').element as HTMLTextAreaElement).value).toBe(
      "上次的答案",
    )
    expect((wrapper.get('[data-testid="doubt-draft"]').element as HTMLTextAreaElement).value).toBe(
      "我的疑问",
    )
    expect((wrapper.get('[data-testid="appeal-draft"]').element as HTMLTextAreaElement).value).toBe(
      "我不同意",
    )
  })

  it("hides the mastery check segment until the session enters that stage", async () => {
    fetchSession.mockResolvedValue(createSession({
      flowStage: "WAIT_STUDENT_ACTION",
      version: 9,
    }))
    const wrapper = await mountSessionView()

    expect(wrapper.get('[data-testid="dialog-segmented"]').text()).not.toContain("掌握度核验")
  })

  it("asks for a mastery check instead of a second full self-explanation", async () => {
    fetchSession.mockResolvedValue(createSession({
      flowStage: "SHOWING_FULL_SOLUTION",
      solutionExposed: true,
      version: 9,
    }))
    const wrapper = await mountSessionView()

    expect(wrapper.get('[data-testid="understood-solution"]').text()).toBe("我会了，进入掌握度核验")
    expect(wrapper.text()).not.toContain("第二轮自讲")
  })

  it("submits mastery check answers and shows the per-question result", async () => {
    fetchSession.mockResolvedValue(createSession({
      flowStage: "WAIT_MASTERY_CHECK",
      version: 9,
      masteryCheck: {
        questions: [
          { id: "mc1", question: "你在合并两个数量时依据的是什么？" },
          { id: "mc2", question: "为什么结果一定是 2？" },
        ],
        answers: null,
        results: null,
        outcome: null,
      },
    }))
    submitMasteryCheckAnswers.mockResolvedValue(createSession({
      flowStage: "WAIT_STUDENT_ACTION",
      status: "NEEDS_REVIEW",
      completionType: "AFTER_MASTERY_CHECK",
      version: 10,
      masteryCheck: {
        questions: [
          { id: "mc1", question: "你在合并两个数量时依据的是什么？" },
          { id: "mc2", question: "为什么结果一定是 2？" },
        ],
        answers: [
          { questionId: "mc1", answer: "依据是把两个 1 合起来。" },
          { questionId: "mc2", answer: "因为 1 加 1 等于 2。" },
        ],
        results: [
          { questionId: "mc1", passed: true, basis: "学生说明了依据。" },
          { questionId: "mc2", passed: false, basis: "学生只是复述了结论。" },
        ],
        outcome: "NEEDS_REVIEW",
      },
    }))
    const wrapper = await mountSessionView()

    expect(wrapper.get('[data-testid="dialog-segmented"]').text()).toContain("掌握度核验")
    await wrapper.get('[data-testid="mastery-answer-mc1"]').setValue("依据是把两个 1 合起来。")
    await wrapper.get('[data-testid="mastery-answer-mc2"]').setValue("因为 1 加 1 等于 2。")
    await wrapper.get('[data-testid="submit-mastery-check"]').trigger("click")
    await flushPromises()

    expect(submitMasteryCheckAnswers).toHaveBeenCalledWith(
      "12",
      [
        { questionId: "mc1", answer: "依据是把两个 1 合起来。" },
        { questionId: "mc2", answer: "因为 1 加 1 等于 2。" },
      ],
      9,
    )
    expect(wrapper.text()).toContain("核验仍有未解决问题，本题结束并记录待复核")
    expect(wrapper.text()).toContain("未通过：学生只是复述了结论。")
  })

  it("requires every mastery check question to be answered before submitting", async () => {
    fetchSession.mockResolvedValue(createSession({
      flowStage: "WAIT_MASTERY_CHECK",
      version: 9,
      masteryCheck: {
        questions: [{ id: "mc1", question: "你在合并两个数量时依据的是什么？" }],
        answers: null,
        results: null,
        outcome: null,
      },
    }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="submit-mastery-check"]').trigger("click")
    await flushPromises()

    expect(submitMasteryCheckAnswers).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain("请先回答全部核验问题再提交")
  })
})
