import { flushPromises, mount } from "@vue/test-utils"
import ElementPlus from "element-plus"
import { createMemoryHistory, createRouter } from "vue-router"
import { beforeEach, describe, expect, it, vi } from "vitest"

import * as sessionApi from "../src/api/sessions"
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
  submitSolutionUnderstanding: vi.fn(),
  submitTextAttempt: vi.fn(),
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
    teachingGeneration: null,
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
  const wrapper = mount(SessionView, { global: { plugins: [ElementPlus, router] } })
  await flushPromises()
  return wrapper
}

describe("SessionView", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    localStorage.clear()
    fetchLearningTimeline.mockResolvedValue([])
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
    expect(wrapper.get('[data-testid="main-draft"]').attributes("disabled")).toBeUndefined()
    expect(wrapper.get('[data-testid="submit-explanation"]')).toBeTruthy()
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
    expect(submitTextAttempt).toHaveBeenCalledWith("12", "1 加 1 等于 2。", 2, undefined)
  })

  it("does not show the voice recorder while submitting an explanation", async () => {
    fetchSession.mockResolvedValue(createSession())
    submitInitialChoice.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT", version: 2, initialChoice: "KNOW" }))
    let resolveTextAttempt: (session: Session) => void = () => undefined
    submitTextAttempt.mockReturnValue(new Promise((resolve) => {
      resolveTextAttempt = resolve
    }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="main-draft"]').setValue("1 加 1 等于 2。")
    const submitPromise = wrapper.get('[data-testid="submit-explanation"]').trigger("click")
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.findAllComponents(VoiceRecorder).filter(
      (recorder) => recorder.props("target") === "SELF_EXPLANATION",
    )).toHaveLength(0)

    resolveTextAttempt(createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 3 }))
    await submitPromise
    await flushPromises()
  })

  it("shows only the direct start-recording entry without voice guidance text", async () => {
    fetchSession.mockResolvedValue(createSession())
    const wrapper = await mountSessionView()

    expect(wrapper.get('[data-testid="start-voice"]').text()).toBe("开始录音")
    expect(wrapper.text()).not.toContain("使用语音自讲")
    expect(wrapper.text()).not.toContain("实时语音输入")
    expect(wrapper.text()).not.toContain("确认语音转写")
  })

  it("appends only final voice transcripts to the editable draft", async () => {
    fetchSession.mockResolvedValue(createSession({ flowStage: "CAPTURING_INPUT" }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="main-draft"]').setValue("我先写下已有条件。")
    wrapper.findComponent(VoiceRecorder).vm.$emit("finalTranscript", "再计算 1 加 1。")
    await flushPromises()

    expect((wrapper.get('[data-testid="main-draft"]').element as HTMLTextAreaElement).value).toBe(
      "我先写下已有条件。\n再计算 1 加 1。",
    )
  })

  it("returns a voice transcript to the editable draft without entering a confirmation stage", async () => {
    fetchSession
      .mockResolvedValueOnce(createSession({ flowStage: "CAPTURING_INPUT", version: 6 }))
      .mockResolvedValueOnce(createSession({
        flowStage: "CAPTURING_INPUT",
        version: 7,
      }))
    submitTextAttempt.mockResolvedValue(createSession({
      flowStage: "WAIT_GUIDED_ANSWERS",
      currentDraft: "学生确认后的文本",
      version: 8,
    }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="main-draft"]').setValue("学生确认后的文本")
    wrapper.findComponent(VoiceRecorder).vm.$emit("completed", 15)
    await flushPromises()

    expect(wrapper.get('[data-testid="start-voice"]').text()).toBe("开始录音")
    await wrapper.get('[data-testid="submit-explanation"]').trigger("click")
    await flushPromises()

    expect(submitTextAttempt).toHaveBeenCalledWith("12", "学生确认后的文本", 7, 15)
    expect(wrapper.text()).not.toContain("实时语音输入")
    expect(wrapper.text()).not.toContain("确认语音转写")
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
        coveredPoints: [],
        missingPoints: ["正确计算加法"],
        errorEvidence: [],
        confidence: 1,
        needHumanReason: null,
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
        coveredPoints: [],
        missingPoints: ["正确计算加法"],
        errorEvidence: [],
        confidence: 1,
        needHumanReason: null,
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
        status: "NEED_HUMAN",
        flowStage: "WAIT_STUDENT_ACTION",
        version: 4,
        needHumanReason: "教学生成失败，会话已进入人工处理",
      }))
    submitTextAttempt.mockRejectedValue(
      new sessionApi.SessionApiError(
        "会话操作失败：教学生成失败，会话已进入人工处理",
        502,
        "TEACHING_GENERATION_FAILED",
        12,
      ),
    )
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="main-draft"]').setValue("我先说明当前思路。")
    await wrapper.get('[data-testid="submit-explanation"]').trigger("click")
    await flushPromises()

    expect(fetchSession).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain("教学生成失败，会话已进入人工处理")
    expect(wrapper.text()).toContain("需要人工处理")
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
  })

  it("shows compact progress and feedback before the self-explanation actions", async () => {
    fetchSession.mockResolvedValue(createSession({
      flowStage: "WAIT_STUDENT_ACTION",
      latestEvaluation: {
        id: 4,
        correctness: "WRONG",
        completeness: "INCOMPLETE",
        coveredPoints: [],
        missingPoints: ["正确计算加法"],
        errorEvidence: [{
          quote: "1 加 1 等于 3。",
          locationDescription: "计算结果",
          reason: "两个 1 相加的结果应为 2。",
          thinkingDirection: "可以用实物计数验证。",
        }],
        confidence: 1,
        needHumanReason: null,
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

    expect(wrapper.text()).toContain("已讲清 0 个关键点，还差 1 个")
    expect(wrapper.text()).toContain("辅助支持 0 次")
    expect(wrapper.text()).not.toContain("本轮支持")
    expect(wrapper.text()).not.toContain("当前学习状态")
    expect(wrapper.text()).not.toContain("进度由系统规则计算")
    expect(wrapper.text()).not.toContain("当前输入与主操作")
    expect(wrapper.text()).not.toContain("内容会自动保存在当前浏览器中")
    expect(wrapper.text()).not.toContain("当前可使用")
    expect(wrapper.text()).toContain("最新反馈")
    expect(wrapper.text()).toContain("下一步：请重新检查两个数相加的结果。")
    expect(wrapper.text()).not.toContain("两个 1 相加的结果应为 2。")
    expect(wrapper.find('[data-testid="request-support"]').exists()).toBe(false)
    expect(wrapper.get(".self-explain-actions").get('[data-testid="submit-explanation"]')).toBeTruthy()
    expect(wrapper.get(".self-explain-actions").get('[data-testid="start-voice"]')).toBeTruthy()
    expect(wrapper.get('[data-testid="dialog-segmented"]').text()).not.toContain("AI说错了")
    expect(wrapper.html().indexOf("最新反馈")).toBeLessThan(
      wrapper.html().indexOf('data-testid="dialog-segmented"'),
    )

    const toggle = wrapper.get('[aria-controls="feedback-details"]')
    expect(toggle.attributes("aria-expanded")).toBe("false")
    await toggle.trigger("click")

    expect(toggle.attributes("aria-expanded")).toBe("true")
    expect(wrapper.text()).toContain("两个 1 相加的结果应为 2。")
  })

  it("shows covered and remaining rubric points as the primary progress", async () => {
    fetchQuestion.mockResolvedValueOnce({
      id: 3,
      evaluationMode: "FULL_RUBRIC",
      questionContent: "综合题",
      standardAnswer: "答案",
      rubricPoints: ["关键点一", "关键点二", "关键点三"],
      commonErrors: [],
      alternativeSolutions: [],
      layeredHints: [],
      guidedQuestions: [],
      fullSolution: "解析",
      archivedAt: null,
      createdAt: "2026-07-20T00:00:00Z",
      updatedAt: "2026-07-20T00:00:00Z",
    })
    fetchSession.mockResolvedValue(createSession({
      coveredPointsCurrentRound: ["关键点一", "关键点二"],
      supportCountRound: 2,
    }))

    const wrapper = await mountSessionView()

    expect(wrapper.get('[data-testid="learning-progress"]').text()).toBe(
      "已讲清 2 个关键点，还差 1 个",
    )
    expect(wrapper.text()).toContain("辅助支持 2 次")
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
        selfExplain: "上次的自讲内容",
        guidedAnswers: { q1: "上次的答案" },
        doubt: "我的疑问",
        appeal: "我不同意",
      }),
    )
    const wrapper = await mountSessionView()

    expect((wrapper.get('[data-testid="main-draft"]').element as HTMLTextAreaElement).value).toBe(
      "上次的自讲内容",
    )
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
})
