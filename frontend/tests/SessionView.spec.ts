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
  askDoubt: vi.fn(),
  confirmVoiceDraft: vi.fn(),
  confirmVoiceAttempt: vi.fn(),
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
const confirmVoiceDraft = vi.mocked(sessionApi.confirmVoiceDraft)
const confirmVoiceAttempt = vi.mocked(sessionApi.confirmVoiceAttempt)
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
    pendingVoiceAttempt: null,
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

  it("keeps the voice transcript editable until the student submits it", async () => {
    fetchSession
      .mockResolvedValueOnce(createSession({ flowStage: "CAPTURING_INPUT", version: 6 }))
      .mockResolvedValueOnce(createSession({
        flowStage: "CONFIRMING_TEXT",
        version: 7,
        pendingVoiceAttempt: {
          id: 15,
          audioFileId: 9,
          asrTranscript: "原始转写",
          voiceTarget: "SELF_EXPLANATION",
          voiceTargetId: null,
        },
      }))
    confirmVoiceAttempt.mockResolvedValue(createSession({
      flowStage: "WAIT_STUDENT_ACTION",
      currentDraft: "学生确认后的文本",
      version: 8,
    }))
    const wrapper = await mountSessionView()

    await wrapper.get('[data-testid="main-draft"]').setValue("学生确认后的文本")
    wrapper.findComponent(VoiceRecorder).vm.$emit("completed")
    await flushPromises()

    expect(confirmVoiceAttempt).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="start-voice"]').text()).toBe("开始录音")
    await wrapper.get('[data-testid="submit-explanation"]').trigger("click")
    await flushPromises()

    expect(confirmVoiceAttempt).toHaveBeenCalledWith("12", 15, "学生确认后的文本", 7)
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

    const guidedRecorders = wrapper.findAllComponents(VoiceRecorder)
    expect(guidedRecorders.map((recorder) => recorder.props("targetId"))).toEqual(["q1", "q2"])
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
    )
    expect(askDoubt).not.toHaveBeenCalled()
    expect(continueExplaining).not.toHaveBeenCalled()
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
        feedback: "请检查。",
        confidence: 1,
        nextAction: "CORRECT_AND_ASK",
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

  it("confirms a doubt voice draft before the doubt button submits it", async () => {
    fetchSession.mockResolvedValue(createSession({
      flowStage: "CONFIRMING_TEXT",
      version: 7,
      pendingVoiceAttempt: {
        id: 16,
        audioFileId: 10,
        asrTranscript: "为什么要相加？",
        voiceTarget: "DOUBT",
        voiceTargetId: null,
      },
    }))
    confirmVoiceDraft.mockResolvedValue(createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 8 }))
    askDoubt.mockResolvedValue(createSession({ flowStage: "WAIT_STUDENT_ACTION", version: 9 }))
    const wrapper = await mountSessionView()

    expect(wrapper.findAllComponents(VoiceRecorder).map((recorder) => recorder.props("target"))).toEqual([
      "DOUBT",
    ])
    await wrapper.get('[data-testid="doubt-draft"]').setValue("修改后的疑问")
    await wrapper.get('[data-testid="submit-doubt"]').trigger("click")
    await flushPromises()

    expect(confirmVoiceDraft).toHaveBeenCalledWith("12", 16, "修改后的疑问", 7)
    expect(askDoubt).toHaveBeenCalledWith("12", "", "修改后的疑问", 8)
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

    expect(wrapper.text()).toContain("自讲记录")
    const contents = wrapper.findAll('[data-testid="timeline-content"]').map((item) => item.text())
    expect(contents).toEqual(["1 加 1 等于 2。", "还需要说明为什么是 2。"])
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
