<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"

import {
  cancelCurrentRun,
  continueExplaining,
  createSession,
  fetchLearningTimeline,
  fetchSessionHistory,
  fetchSession,
  SessionApiError,
  submitAppeal,
  submitGuidedAnswers,
  submitInitialChoice,
  submitMasteryCheckAnswers,
  submitSolutionUnderstanding,
} from "../api/sessions"
import { acknowledgeGrading, fetchGrading, retryGrading, submitGradedStepAttempt } from "../api/grading"
import { fetchIndependentDoubts, startIndependentDoubt, type IndependentDoubt } from "../api/doubts"
import { AIStreamError, registerAIStreamListener, subscribeAIRun, type AIRunSnapshot } from "../api/ai-stream"
import {
  fetchSessionSteps,
  submitStepAttempt,
} from "../api/session-steps"
import FormulaEditor from "../components/FormulaEditor.vue"
import StudentInputActions from "../components/StudentInputActions.vue"
import VoiceRecorder from "../components/VoiceRecorder.vue"
import TeacherSpeechPlayer from "../components/TeacherSpeechPlayer.vue"
import TeacherReplyCard from "../components/TeacherReplyCard.vue"
import { fetchQuestion } from "../api/questions"
import { authUser } from "../stores/auth"
import type {
  GuidedAnswer,
  InitialChoice,
  LearningTimelineItem,
  Session,
  SessionHistoryItem,
  FlowStage,
  VoiceInputTarget,
} from "../types/session"
import type { StepsResponse } from "../types/session-step"
import type { Question } from "../types/question"
import type { Grading } from "../types/grading"
import FirstExplanationGrading from "../components/FirstExplanationGrading.vue"
import { sanitizeQuestionHtml } from "../utils/questionHtml"
import { renderStudentTextHtml } from "../utils/studentTextHtml"

type SegmentKey = "selfExplain" | "guidedAnswers" | "masteryCheck" | "doubt" | "appeal"

interface DialogDrafts {
  guidedAnswers: Record<string, string>
  masteryCheck: Record<string, string>
  doubt: string
  appeal: string
  lastSubmittedSelfExplanation: string
  selfExplanation: string | null
}

const route = useRoute()
const router = useRouter()
const session = ref<Session>()
const question = ref<Question>()
const timeline = ref<LearningTimelineItem[]>([])
const firstGradingSubmissionText = computed(() => {
  const submittedSteps = grading.value?.studentSteps?.map((step) =>
    [step.stepContent, step.explainTranscript].filter(Boolean).join("\n"),
  ).filter(Boolean).join("\n")
  if (submittedSteps) return submittedSteps
  const gradedAt = grading.value ? new Date(grading.value.createdAt).getTime() : Infinity
  return timeline.value.filter((item) => item.eventType === "SUBMISSION"
    && item.submissionType === "SELF_EXPLANATION"
    && new Date(item.createdAt).getTime() <= gradedAt).at(-1)?.content ?? ""
})
const grading = ref<Grading | null>(null)
const gradingRetrying = ref(false)
const streamSnapshot = ref<AIRunSnapshot | null>(null)
const gradingStreamRunId = ref<string>()
const gradingDismissed = ref(false)
const awaitingFirstGrading = ref(false)
let detachStreamListener: (() => void) | undefined
let pageDetached = false
const gradingPreviewFields = computed(() => {
  if (!streamSnapshot.value || ["FAILED", "CANCELLED"].includes(streamSnapshot.value.status)) return {}
  const channel = streamSnapshot.value.channels.FIRST_EXPLANATION_GRADING
  return channel && channel.status !== "FAILED" ? channel.fields : {}
})
let gradingPollTimer: ReturnType<typeof setInterval> | undefined
let gradingPollInFlight = false
const gradingPollError = ref("")
const activeSegment = ref<SegmentKey>("selfExplain")
const currentStepId = ref<number | null>(null)
const currentStepContent = ref("")
const currentStepTranscript = ref("")
// 上次成功提交时自讲框里的内容，用于在当前会话内回填，方便学生直接修改后重讲。
const lastSubmittedSelfExplanation = ref("")
const formulaEditorRef = ref<InstanceType<typeof FormulaEditor>>()
const doubtFormulaEditorRef = ref<InstanceType<typeof FormulaEditor>>()
const guidedFormulaEditorRefs = ref<Record<string, InstanceType<typeof FormulaEditor>>>({})
const masteryFormulaEditorRefs = ref<Record<string, InstanceType<typeof FormulaEditor>>>({})
const guidedAnswerText = ref<Record<string, string>>({})
const masteryAnswerText = ref<Record<string, string>>({})
const doubtDraft = ref("")
const independentDoubts = ref<IndependentDoubt[]>([])
const doubtPreviews = ref<Record<string, string>>({})
const doubtHistoryError = ref("")
const doubtControllers = new Map<string, AbortController>()
const appealDraft = ref("")
const loading = ref(true)
const submitting = ref(false)
const doubtSubmitting = ref(false)
const cancelling = ref(false)
const activeAiRequest = ref<{ runId: string; controller: AbortController; previousStage: FlowStage } | null>(null)
let aiRequestGeneration = 0
let gradingPollGeneration = 0
// 自讲请求进行时允许编辑下一份草稿；准备步骤和失败刷新时仍锁定输入。
const explanationSubmitting = ref(false)
const teacherReplyRequested = ref(false)
const previousReplySupport = ref<Session["latestSupport"]>()
const errorMessage = ref("")
const voiceRecording = ref(false)
const activeVoiceKey = ref<string>()
const voiceAttemptIds = ref<Record<string, number>>({})
const doubtVoiceRecorderRef = ref<InstanceType<typeof VoiceRecorder>>()
const stepVoiceRecorderRef = ref<InstanceType<typeof VoiceRecorder>>()
const explainVoiceRecorderRef = ref<InstanceType<typeof VoiceRecorder>>()
const guidedVoiceRecorderRefs = ref<InstanceType<typeof VoiceRecorder>[]>([])
const masteryVoiceRecorderRefs = ref<InstanceType<typeof VoiceRecorder>[]>([])
const appealVoiceRecorderRef = ref<InstanceType<typeof VoiceRecorder>>()
const historyDrawerVisible = ref(false)
const historyItems = ref<SessionHistoryItem[]>([])
const historyLoading = ref(false)
const historyError = ref("")
const teacherSpeechRef = ref<InstanceType<typeof TeacherSpeechPlayer>>()
let pendingSpeechIds: string[] = []
let speechGeneration = 0

function isSpokenReply(item: LearningTimelineItem) {
  if (item.speaker !== "AI" || !item.content.trim()) return false
  if (item.eventType === "EVALUATION") return Boolean(item.action && item.action !== "COMPLETE")
  return ["SUPPORT", "GUIDED_QUESTIONS", "FOLLOW_UP", "MASTERY_QUESTIONS", "MASTERY_RESULT"].includes(item.eventType)
}

// 手动播放定位最近一轮老师回复；初次加载历史只设置目标，不触发播放。
const teacherReplyIds = computed(() => {
  const items = visibleTimeline.value
  let lastReply = items.length - 1
  while (lastReply >= 0 && !isSpokenReply(items[lastReply])) lastReply -= 1
  if (lastReply < 0) return []
  let start = lastReply
  while (start > 0 && items[start - 1].speaker !== "STUDENT") start -= 1
  return items.slice(start, lastReply + 1).filter(isSpokenReply).map((item) => item.id)
})

const canShowTeachingContent = computed(() => (!grading.value && !awaitingFirstGrading.value)
  || gradingDismissed.value || Boolean(grading.value?.acknowledgedAt))
const teachingEvaluationPending = computed(() => session.value?.flowStage === "AI_EVALUATING"
  || Boolean(grading.value && ["PENDING", "RUNNING"].includes(grading.value.evaluationStatus)))
const cancellableRunId = computed(() => activeAiRequest.value?.runId || session.value?.activeRunId || null)
const runPending = computed(() => Boolean(cancellableRunId.value))
// 查看自讲不受流程限制；子问题、核验、解析、暂停和终态只允许查看。
const selfExplanationReadOnly = computed(() => session.value?.status !== "IN_PROGRESS"
  || ["WAIT_GUIDED_ANSWERS", "WAIT_MASTERY_CHECK", "SHOWING_FULL_SOLUTION"].includes(session.value.flowStage))
const selfExplanationEditingDisabled = computed(() => selfExplanationReadOnly.value
  || cancelling.value || (submitting.value && !explanationSubmitting.value && !teachingEvaluationPending.value))
const canSubmitSelfExplanation = computed(() => session.value?.status === "IN_PROGRESS"
  && ["WAIT_INITIAL_CHOICE", "CAPTURING_INPUT", "WAIT_STUDENT_ACTION"].includes(session.value.flowStage)
  && !submitting.value && !cancelling.value && !runPending.value && !teachingEvaluationPending.value)
const showGuidedAnswers = computed(() => session.value?.status === "IN_PROGRESS"
  && session.value.flowStage === "WAIT_GUIDED_ANSWERS" && canShowTeachingContent.value
  && Boolean(session.value.latestSupport?.guidedQuestions?.length))
const visibleTimeline = computed(() => canShowTeachingContent.value ? timeline.value : timeline.value.filter((item) => item.speaker === "STUDENT"))
const speechIsSolution = computed(() => Boolean(session.value?.solutionExposed && question.value?.fullSolution
  && canShowTeachingContent.value
  && !masteryCheckCompleted()
  && (session.value.flowStage === "SHOWING_FULL_SOLUTION"
    || ["NEEDS_REVIEW", "STOPPED_LIMIT"].includes(session.value.status))))
const currentReplySupport = computed(() => {
  // 新请求的会话快照可能仍携带上一轮反馈，当前回复区只展示新增或更新的内容。
  const support = session.value?.latestSupport
  const previous = previousReplySupport.value
  if (previous && support?.id === previous.id && support.content === previous.content && support.followUpContent === previous.followUpContent) return null
  return support
})
const nextStepText = computed(() => speechIsSolution.value || masteryCheckCompleted() || !canShowTeachingContent.value ? ""
  : currentReplySupport.value?.followUpContent || currentReplySupport.value?.content || "")
const teacherReplyPending = computed(() => (teacherReplyRequested.value && streamSnapshot.value?.status !== "SUCCEEDED") || teachingEvaluationPending.value)
const teacherReplyBlocks = computed(() => {
  if (!canShowTeachingContent.value) return []
  if (teacherReplyPending.value) {
    if (streamSnapshot.value?.status !== "RUNNING") return []
    return Object.entries(streamSnapshot.value.channels).flatMap(([purpose, channel]) => {
      if (channel.status === "FAILED") return []
      return Object.entries(channel.fields).flatMap(([field, text]) => {
        if (!text.trim()) return []
        const question = /^questions\.(\d+)\.question$/.exec(field)
        const basis = /^results\.(\d+)\.basis$/.exec(field)
        let label: string
        if (["AI_TEACHING", "AI_SUPPORT", "GUIDED_ANSWER_ASSESSMENT"].includes(purpose) && field === "content") label = "下一步"
        else if (["AI_TEACHING", "AI_SUPPORT", "AI_MASTERY_CHECK"].includes(purpose) && question) label = `${purpose === "AI_MASTERY_CHECK" ? "核验问题" : "子问题"} ${Number(question[1]) + 1}`
        else if (purpose === "MASTERY_CHECK_ASSESSMENT" && basis) label = `核验依据 ${Number(basis[1]) + 1}`
        else return []
        return [{ key: `${purpose}:${field}`, label, text }]
      })
    })
  }
  const blocks = nextStepText.value ? [{ key: "content", label: "下一步", text: nextStepText.value }] : []
  if (session.value?.flowStage === "WAIT_GUIDED_ANSWERS") {
    blocks.push(...(session.value.latestSupport?.guidedQuestions ?? []).map((item, index) => ({ key: item.id, label: `子问题 ${index + 1}`, text: item.question })))
  } else if (session.value?.flowStage === "WAIT_MASTERY_CHECK" && !masteryCheckCompleted()) {
    blocks.push(...(session.value.masteryCheck?.questions ?? []).map((item, index) => ({ key: item.id, label: `核验问题 ${index + 1}`, text: item.question })))
  }
  return blocks
})
const showTeacherReply = computed(() => teacherReplyPending.value || Boolean(session.value && (
  currentReplySupport.value || session.value.masteryCheck?.questions?.length
  || session.value.flowStage === "SHOWING_FULL_SOLUTION" || isTerminalSession()
)))
const speechControlsTarget = computed(() => {
  if (activeSegment.value === "masteryCheck" && canShowTeachingContent.value
    && session.value?.masteryCheck?.questions?.length) return "#mastery-check-speech-controls"
  if (activeSegment.value === "doubt") return "#doubt-speech-controls"
  if (activeSegment.value === "selfExplain") return "#self-explain-speech-controls"
  if (activeSegment.value === "guidedAnswers" && showGuidedAnswers.value
    && session.value?.latestSupport?.guidedQuestions?.length) return "#guided-answer-speech-controls"
  if (teacherReplyPending.value) return undefined
  if (canShowTeachingContent.value && masteryCheckCompleted()) return "#mastery-result-speech"
  if (nextStepText.value) return "#next-step-speech"
  if (speechIsSolution.value) return "#solution-speech"
  if (canShowTeachingContent.value && session.value?.masteryCheck?.questions?.length && !isTerminalSession()) return "#mastery-speech"
  if (canShowTeachingContent.value && session.value?.latestSupport?.guidedQuestions?.length && !isTerminalSession()) return "#guided-speech"
  return teacherReplyIds.value.length ? "#latest-reply-speech" : undefined
})

function stopTeacherSpeech() {
  speechGeneration += 1
  pendingSpeechIds = []
  teacherSpeechRef.value?.stop()
}

function prepareReplyRecording() {
  stopTeacherSpeech()
  return true
}

watch(submitting, (busy) => {
  if (busy) stopTeacherSpeech()
}, { flush: "sync" })

watch([submitting, voiceRecording, canShowTeachingContent, teacherReplyIds], async ([busy, recording, visible, replyIds], [, , previouslyVisible, previousIds]) => {
  // 关闭评分时播放已生成的回复；随后由流式或轮询加载的新回复也在此排队，历史加载保持静音。
  if (visible && !loading.value) {
    const knownIds = new Set(previouslyVisible ? previousIds : [])
    const newIds = replyIds.filter((id) => !knownIds.has(id))
    pendingSpeechIds = [...new Set([...pendingSpeechIds, ...newIds])]
  }
  if (busy || recording || !visible) return
  const ids = pendingSpeechIds
  const generation = speechGeneration
  pendingSpeechIds = []
  if (!ids.length) return
  await nextTick()
  if (generation === speechGeneration && canShowTeachingContent.value && !submitting.value && !voiceRecording.value) {
    void teacherSpeechRef.value?.playReply(ids)
  }
}, { flush: "post" })

const sessionId = String(route.params.sessionId)
const pendingAIRunStorageKey = `ai-self-explain:session:${sessionId}:pending-ai-run`
const dialogDraftStorageKey = `ai-self-explain:session:${sessionId}:dialog-drafts`
let dialogDraftsReady = false

const segmentEntries: Array<{ label: string; value: SegmentKey }> = [
  { label: "自讲", value: "selfExplain" },
  { label: "回答子问题", value: "guidedAnswers" },
  { label: "掌握度核验", value: "masteryCheck" },
  { label: "我有疑问", value: "doubt" },
]

const studentInterruptionFlowStages = new Set<Session["flowStage"]>([
  "WAIT_INITIAL_CHOICE",
  "CAPTURING_INPUT",
  "WAIT_STUDENT_ACTION",
  "WAIT_GUIDED_ANSWERS",
  "SHOWING_FULL_SOLUTION",
])

// 终态与后端规则层保持一致：结束后的会话不再接受新的学生动作。
const terminalStatuses = new Set<Session["status"]>(["COMPLETED", "STOPPED_LIMIT", "NEEDS_REVIEW"])

const actionLabels: Record<NonNullable<LearningTimelineItem["action"]>, string> = {
  COMPLETE: "本轮完成",
  ASK_FOCUSED_QUESTION: "聚焦追问",
  GIVE_CORRECTION: "纠错",
  CORRECT_AND_ASK: "纠错与追问",
  GIVE_HINT: "提示",
}

const timelineEventLabels: Record<LearningTimelineItem["eventType"], string> = {
  SUBMISSION: "学生提交",
  EVALUATION: "学习反馈",
  SUPPORT: "学习支持",
  GUIDED_QUESTIONS: "子问题",
  FOLLOW_UP: "整合引导",
  MASTERY_QUESTIONS: "掌握度核验问题",
  MASTERY_ANSWER: "核验回答",
  MASTERY_RESULT: "核验结论",
  FULL_SOLUTION: "完整解析",
  NEED_HUMAN: "人工复核已申请",
}

const speakerLabels: Record<LearningTimelineItem["speaker"], string> = {
  STUDENT: "学生",
  AI: "AI",
  SYSTEM: "系统",
}

const submissionTypeLabels: Record<NonNullable<LearningTimelineItem["submissionType"]>, string> = {
  SELF_EXPLANATION: "自讲",
  SUPPORT_REQUEST: "请求提示",
  GUIDED_ANSWER: "回答子问题",
  DOUBT: "我有疑问",
  APPEAL: "AI说错了",
  MASTERY_ANSWER: "核验回答",
}

const masteryOutcomeLabels: Record<"COMPLETED" | "NEEDS_REVIEW", string> = {
  COMPLETED: "核验通过，本题学习成功",
  NEEDS_REVIEW: "核验仍有未解决问题，本题结束并记录待复核",
}

const historyStatusLabels: Record<SessionHistoryItem["status"], string> = {
  IN_PROGRESS: "进行中",
  COMPLETED: "已完成",
  STOPPED_LIMIT: "已停止",
  PAUSED: "已暂停",
  NEEDS_REVIEW: "待复核",
}

function historyStatusType(status: SessionHistoryItem["status"]): "success" | "warning" | "info" {
  if (status === "COMPLETED") return "success"
  if (status === "IN_PROGRESS" || status === "PAUSED") return "warning"
  return "info"
}

function formatHistoryCreatedAt(createdAt: string) {
  return new Date(createdAt).toLocaleString("zh-CN", { hour12: false })
}

function emptyDialogDrafts(): DialogDrafts {
  return {
    guidedAnswers: {},
    masteryCheck: {},
    doubt: "",
    appeal: "",
    lastSubmittedSelfExplanation: "",
    selfExplanation: null,
  }
}

async function openHistoryDrawer() {
  historyDrawerVisible.value = true
  historyLoading.value = true
  historyError.value = ""
  try {
    historyItems.value = await fetchSessionHistory()
  } catch (error) {
    historyError.value = error instanceof Error ? error.message : String(error)
  } finally {
    historyLoading.value = false
  }
}

async function selectHistoryItem(item: SessionHistoryItem) {
  historyDrawerVisible.value = false
  if (item.id !== Number(sessionId)) {
    await router.push(`/sessions/${item.id}`)
  }
}

function readDialogDrafts(): { hasStoredDrafts: boolean; drafts: DialogDrafts } {
  const savedDrafts = localStorage.getItem(dialogDraftStorageKey)
  if (!savedDrafts) {
    return { hasStoredDrafts: false, drafts: emptyDialogDrafts() }
  }
  try {
    const parsed = JSON.parse(savedDrafts) as Partial<DialogDrafts>
    return {
      hasStoredDrafts: true,
      drafts: {
        guidedAnswers: parsed.guidedAnswers && typeof parsed.guidedAnswers === "object"
          ? parsed.guidedAnswers
          : {},
        masteryCheck: parsed.masteryCheck && typeof parsed.masteryCheck === "object"
          ? parsed.masteryCheck
          : {},
        doubt: typeof parsed.doubt === "string" ? parsed.doubt : "",
        appeal: typeof parsed.appeal === "string" ? parsed.appeal : "",
        lastSubmittedSelfExplanation: typeof parsed.lastSubmittedSelfExplanation === "string"
          ? parsed.lastSubmittedSelfExplanation
          : "",
        selfExplanation: typeof parsed.selfExplanation === "string" ? parsed.selfExplanation : null,
      },
    }
  } catch (error) {
    console.error("读取分段草稿失败", error)
    return { hasStoredDrafts: false, drafts: emptyDialogDrafts() }
  }
}

function persistDialogDrafts() {
  if (!dialogDraftsReady) return
  localStorage.setItem(
    dialogDraftStorageKey,
    JSON.stringify({
      guidedAnswers: guidedAnswerText.value,
      masteryCheck: masteryAnswerText.value,
      doubt: doubtDraft.value,
      appeal: appealDraft.value,
      lastSubmittedSelfExplanation: lastSubmittedSelfExplanation.value,
      selfExplanation: currentStepContent.value,
    }),
  )
}

function applyStoredDialogDrafts() {
  const savedDraftState = readDialogDrafts()
  guidedAnswerText.value = savedDraftState.drafts.guidedAnswers
  masteryAnswerText.value = savedDraftState.drafts.masteryCheck
  doubtDraft.value = savedDraftState.drafts.doubt
  appealDraft.value = savedDraftState.drafts.appeal
  lastSubmittedSelfExplanation.value = savedDraftState.drafts.lastSubmittedSelfExplanation
  if (savedDraftState.drafts.selfExplanation !== null) {
    currentStepContent.value = savedDraftState.drafts.selfExplanation
  }
  dialogDraftsReady = true
  return savedDraftState.drafts.selfExplanation !== null
}

watch(
  [guidedAnswerText, masteryAnswerText, doubtDraft, appealDraft, lastSubmittedSelfExplanation, currentStepContent],
  persistDialogDrafts,
  { deep: true },
)

function clearStepState() {
  currentStepId.value = null
  currentStepTranscript.value = ""
}

function applyStepsResponse(response: StepsResponse) {
  currentStepId.value = response.currentStepId
  currentStepContent.value = response.step?.stepContent ?? ""
  currentStepTranscript.value = response.step?.explainTranscript ?? ""
  if (session.value) {
    session.value = {
      ...session.value,
      currentStepId: response.currentStepId,
      version: response.version,
    }
  }
}

async function loadCurrentSteps(preserveContent = false) {
  if (!session.value || session.value.flowStage !== "CAPTURING_INPUT") return
  const generation = aiRequestGeneration
  const response = await fetchSessionSteps(sessionId, "current")
  if (generation !== aiRequestGeneration) return
  const draftContent = currentStepContent.value
  applyStepsResponse(response)
  if (preserveContent) currentStepContent.value = draftContent
}

// 服务端已有步骤内容时以服务端为准，避免旧内容覆盖学生已保存的步骤。
function restoreLastSubmittedExplanation() {
  if (!currentStepContent.value.trim()) {
    currentStepContent.value = lastSubmittedSelfExplanation.value
  }
}

async function loadSessionData(cancelledRun?: { runId: string; minVersion: number }) {
  stopTeacherSpeech()
  const loadedSession = await fetchSession(sessionId)
  if (cancelledRun && (loadedSession.version < cancelledRun.minVersion
    || loadedSession.activeRunId === cancelledRun.runId)) {
    throw new Error("中断已受理，等待会话状态同步，请稍后刷新")
  }
  session.value = loadedSession
  const preserveDraft = dialogDraftsReady || applyStoredDialogDrafts()
  for (const answer of loadedSession.latestSupport?.guidedAnswers ?? []) {
    if (!guidedAnswerText.value[answer.questionId]) {
      guidedAnswerText.value[answer.questionId] = answer.answer
    }
  }
  for (const answer of loadedSession.masteryCheck?.answers ?? []) {
    if (!masteryAnswerText.value[answer.questionId]) {
      masteryAnswerText.value[answer.questionId] = answer.answer
    }
  }
  if (loadedSession.flowStage === "CAPTURING_INPUT") {
    await loadCurrentSteps(preserveDraft)
    if (!preserveDraft) restoreLastSubmittedExplanation()
  } else {
    clearStepState()
    // 提交后会话停在 WAIT_STUDENT_ACTION 等阶段，服务端没有可读的当前步骤，
    // 刷新页面后用上次提交的内容回填；输入框已有内容时保留学生当前输入。
    if (!preserveDraft && !currentStepContent.value.trim()) {
      currentStepContent.value = lastSubmittedSelfExplanation.value
    }
  }
  syncActiveSegmentWithStage()
  const [loadedQuestion, loadedTimeline] = await Promise.all([
    fetchQuestion(String(loadedSession.questionId)), fetchLearningTimeline(sessionId),
  ])
  question.value = loadedQuestion
  timeline.value = loadedTimeline
  if (!preserveDraft && !currentStepContent.value.trim()) {
    currentStepContent.value = loadedTimeline.filter((item) => item.eventType === "SUBMISSION"
      && item.submissionType === "SELF_EXPLANATION").at(-1)?.content ?? ""
  }
  persistDialogDrafts()
  const hasFormalSubmission = loadedTimeline.some((item) => item.eventType === "SUBMISSION" && item.submissionType === "SELF_EXPLANATION")
  grading.value = hasFormalSubmission ? await fetchGrading(sessionId) : null
  const pendingRunId = loadedSession.activeRunId || localStorage.getItem(pendingAIRunStorageKey)
  if (pendingRunId && !activeAiRequest.value && !cancelling.value) {
    void restoreAIStream(pendingRunId)
  } else if (!loadedSession.activeRunId && grading.value && (["PENDING", "RUNNING"].includes(grading.value.status)
    || ["PENDING", "RUNNING"].includes(grading.value.evaluationStatus))) startGradingPolling()
}

async function reloadAfterVersionConflict(
  draftContent: string,
) {
  try {
    await loadSessionData()
    if (session.value?.flowStage === "CAPTURING_INPUT") {
      currentStepContent.value = draftContent
    }
    errorMessage.value = "会话版本已变化，已刷新当前步骤，请确认后重试"
  } catch (refreshError) {
    errorMessage.value = refreshError instanceof Error
      ? refreshError.message
      : String(refreshError)
  }
}

function isVersionConflict(error: unknown): boolean {
  return error instanceof SessionApiError && error.status === 409
}

async function handleAIRequestFailure(error: unknown, draftContent = "") {
  if (!(error instanceof SessionApiError)
    || !["AI_SERVICE_UNAVAILABLE", "AI_OPERATION_FAILED"].includes(error.code ?? "")) {
    return false
  }
  if (draftContent.trim()) {
    lastSubmittedSelfExplanation.value = draftContent
  }
  const draftStepId = currentStepId.value
  const localStepContent = currentStepContent.value
  const localStepTranscript = currentStepTranscript.value
  try {
    await loadSessionData()
    if (session.value?.flowStage === "CAPTURING_INPUT" && currentStepId.value === draftStepId) {
      currentStepContent.value = localStepContent
      currentStepTranscript.value = localStepTranscript
    }
  } catch (refreshError) {
    console.error("AI 服务调用失败后刷新会话失败", refreshError)
  }
  errorMessage.value = error.code === "AI_SERVICE_UNAVAILABLE"
    ? "AI服务调用失败，请稍后再试"
    : error.message
  return true
}

onMounted(async () => {
  try {
    await loadSessionData()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
  if (session.value && !pageDetached) await loadIndependentDoubts()
})

async function pollGrading() {
  if (gradingPollInFlight || submitting.value || voiceRecording.value || cancelling.value) return
  gradingPollInFlight = true
  const generation = gradingPollGeneration
  const aiGeneration = aiRequestGeneration
  try {
    const [nextGrading, nextSession, nextTimeline] = await Promise.all([fetchGrading(sessionId), fetchSession(sessionId), fetchLearningTimeline(sessionId)])
    if (generation !== gradingPollGeneration || aiGeneration !== aiRequestGeneration) return
    grading.value = nextGrading; session.value = nextSession; timeline.value = nextTimeline; gradingPollError.value = ""
    if (nextGrading && ["SUCCEEDED", "FAILED"].includes(nextGrading.status) && ["SUCCEEDED", "FAILED"].includes(nextGrading.evaluationStatus)) stopGradingPolling()
  } catch (error) { if (generation === gradingPollGeneration && aiGeneration === aiRequestGeneration) gradingPollError.value = error instanceof Error ? error.message : String(error) } finally { gradingPollInFlight = false }
}
function startGradingPolling() { if (gradingPollTimer) return; void pollGrading(); gradingPollTimer = setInterval(() => { void pollGrading() }, 2000) }
function stopGradingPolling() { gradingPollGeneration += 1; if (gradingPollTimer) clearInterval(gradingPollTimer); gradingPollTimer = undefined }
async function acknowledgeGradingResult() { if (!grading.value) return; try { grading.value = await acknowledgeGrading(sessionId) } catch (error) { errorMessage.value = error instanceof Error ? error.message : String(error) } }
async function retryGradingResult() {
  if (cancelling.value || !session.value) return
  gradingRetrying.value = true
  const request = beginAIRequest()
  try {
    const nextGrading = await retryGrading(sessionId, request.runId, request.controller.signal)
    if (!isActiveAIRequest(request)) return
    grading.value = nextGrading
    const nextSession = await fetchSession(sessionId)
    if (!isActiveAIRequest(request)) return
    session.value = nextSession
    if (isActiveAIRequest(request)) startGradingPolling()
  } catch (error) {
    if (isActiveAIRequest(request)) errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    if (isActiveAIRequest(request)) { activeAiRequest.value = null; gradingRetrying.value = false }
  }
}

function updateStreamPreview(snapshot: AIRunSnapshot) {
  if (!isActiveAIRequest(snapshot)) return
  streamSnapshot.value = snapshot
  if (snapshot.status !== "RUNNING") localStorage.removeItem(pendingAIRunStorageKey)
  if (snapshot.channels.FIRST_EXPLANATION_GRADING) gradingStreamRunId.value = snapshot.runId
  const result = snapshot.result as { session?: Session; grading?: Grading; flowStage?: FlowStage; report?: unknown } | null
  if (result?.grading) grading.value = result.grading
  if (result?.session) session.value = result.session
  else if (snapshot.status === "SUCCEEDED" && result?.flowStage) session.value = result as Session
  else if (snapshot.status === "SUCCEEDED" && result && "report" in result) grading.value = result as Grading
}

function beginAIRequest(runId: string = crypto.randomUUID(), restoring = false) {
  const request = {
    runId,
    controller: new AbortController(),
    previousStage: session.value!.flowStage,
  }
  aiRequestGeneration += 1
  detachStreamListener?.()
  streamSnapshot.value = null
  activeAiRequest.value = request
  if (!gradingRetrying.value) {
    // 恢复订阅时会话可能已包含本次最终回复，不能把它当作上一轮内容过滤。
    previousReplySupport.value = restoring ? undefined : session.value?.latestSupport
    teacherReplyRequested.value = true
  }
  localStorage.setItem(pendingAIRunStorageKey, runId)
  detachStreamListener = registerAIStreamListener(sessionId, request.runId, updateStreamPreview)
  return request
}

watch(activeAiRequest, (request) => {
  if (request) return
  teacherReplyRequested.value = false
  detachStreamListener?.(); detachStreamListener = undefined
  awaitingFirstGrading.value = false
  if (!pageDetached) {
    if (!streamSnapshot.value || streamSnapshot.value.status !== "RUNNING") localStorage.removeItem(pendingAIRunStorageKey)
    if (streamSnapshot.value?.status === "RUNNING") streamSnapshot.value = null
  }
}, { flush: "sync" })

async function restoreAIStream(runId: string) {
  const request = beginAIRequest(runId, true)
  submitting.value = true
  try {
    await subscribeAIRun(sessionId, runId, { signal: request.controller.signal })
    if (!isActiveAIRequest(request)) return
    syncActiveSegmentWithStage()
    await refreshTimeline()
    grading.value = await fetchGrading(sessionId)
  } catch (error) {
    if (!isActiveAIRequest(request)) return
    streamSnapshot.value = null
    errorMessage.value = error instanceof Error ? error.message : String(error)
    try {
      const [nextSession, nextGrading, nextTimeline] = await Promise.all([fetchSession(sessionId), fetchGrading(sessionId), fetchLearningTimeline(sessionId)])
      if (!isActiveAIRequest(request)) return
      session.value = nextSession; grading.value = nextGrading; timeline.value = nextTimeline
    } catch (refreshError) {
      if (isActiveAIRequest(request)) errorMessage.value += `；刷新会话失败：${refreshError instanceof Error ? refreshError.message : String(refreshError)}`
    }
  } finally {
    if (isActiveAIRequest(request)) { activeAiRequest.value = null; submitting.value = false }
  }
}

function isActiveAIRequest(request: { runId: string }) {
  return activeAiRequest.value?.runId === request.runId && !cancelling.value
}

async function stopCurrentRun() {
  const runId = cancellableRunId.value
  if (!runId || cancelling.value || !session.value) return
  const previousSession = session.value
  const previousStage = activeAiRequest.value?.previousStage
  const requestToAbort = activeAiRequest.value
  cancelling.value = true
  aiRequestGeneration += 1
  stopGradingPolling()
  streamSnapshot.value = null
  localStorage.removeItem(pendingAIRunStorageKey)
  activeAiRequest.value = null
  submitting.value = false
  explanationSubmitting.value = false
  gradingRetrying.value = false
  errorMessage.value = ""
  stopTeacherSpeech()
  if (previousStage) session.value = { ...previousSession, flowStage: previousStage }
  const currentDraft = currentStepContent.value
  const currentTranscript = currentStepTranscript.value
  try {
    session.value = await cancelCurrentRun(sessionId, runId)
    requestToAbort?.controller.abort()
    if (grading.value && (["PENDING", "RUNNING"].includes(grading.value.status)
      || ["PENDING", "RUNNING"].includes(grading.value.evaluationStatus))) grading.value = null
    try {
      await loadSessionData({ runId, minVersion: session.value.version })
    } catch (refreshError) {
      errorMessage.value = refreshError instanceof Error ? refreshError.message : String(refreshError)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
    try {
      await loadSessionData()
    } catch (refreshError) {
      session.value = { ...previousSession, flowStage: "AI_EVALUATING", activeRunId: runId }
      console.error("中断失败后刷新会话失败", refreshError)
    }
  } finally {
    currentStepContent.value = currentDraft
    currentStepTranscript.value = currentTranscript
    cancelling.value = false
  }
}

async function refreshTimeline() {
  const generation = aiRequestGeneration
  const refreshedTimeline = await fetchLearningTimeline(sessionId)
  if (generation !== aiRequestGeneration) return
  timeline.value = refreshedTimeline
}

function timelineTitle(item: LearningTimelineItem) {
  if (item.submissionType) return submissionTypeLabels[item.submissionType]
  return item.action ? actionLabels[item.action] : timelineEventLabels[item.eventType]
}

function timelineItemClass(item: LearningTimelineItem) {
  return {
    "is-student": item.speaker === "STUDENT",
    "is-ai": item.speaker === "AI",
    "is-system": item.speaker === "SYSTEM",
  }
}

function canUseSegment(segment: SegmentKey) {
  if (segment === "selfExplain" || segment === "doubt") return Boolean(session.value)
  if (!session.value || submitting.value || cancelling.value || runPending.value) return false
  if (segment === "guidedAnswers") return showGuidedAnswers.value
  if (segment === "masteryCheck") return session.value.status === "IN_PROGRESS" && session.value.flowStage === "WAIT_MASTERY_CHECK"
  return hasAppealableAiResponse() && canSubmitStudentInterruption()
}

// 掌握度核验只在进入核验阶段后出现，其他阶段不提前暴露该入口。
const segmentOptions = computed(() => segmentEntries
  .filter((segment) => segment.value !== "guidedAnswers" || showGuidedAnswers.value)
  .filter((segment) => segment.value !== "masteryCheck"
    || session.value?.flowStage === "WAIT_MASTERY_CHECK")
  .map((segment) => ({
    ...segment,
    disabled: !canUseSegment(segment.value),
  })))

function syncActiveSegmentWithStage() {
  if (activeSegment.value === "doubt") return
  if (showGuidedAnswers.value) {
    activeSegment.value = "guidedAnswers"
  } else if (session.value?.status === "IN_PROGRESS" && session.value.flowStage === "WAIT_MASTERY_CHECK") {
    activeSegment.value = "masteryCheck"
  } else if (activeSegment.value === "guidedAnswers" || activeSegment.value === "masteryCheck") {
    activeSegment.value = "selfExplain"
  }
}

watch([showGuidedAnswers, () => session.value?.flowStage, () => session.value?.status], syncActiveSegmentWithStage)

function canSubmitStudentInterruption() {
  return !cancelling.value && !runPending.value && session.value?.status === "IN_PROGRESS"
    && studentInterruptionFlowStages.has(session.value.flowStage)
}

function isTerminalSession() {
  return session.value ? terminalStatuses.has(session.value.status) : false
}

function hasAppealableAiResponse() {
  return Boolean(session.value?.latestEvaluation || session.value?.latestSupport)
}

async function continueAfterError() {
  loading.value = true
  errorMessage.value = ""
  try {
    await loadSessionData()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function restartSelfExplanation() {
  if (!session.value) return
  submitting.value = true
  errorMessage.value = ""
  try {
    const restartedSession = await createSession(String(session.value.questionId), true)
    localStorage.removeItem(dialogDraftStorageKey)
    await router.push(`/sessions/${restartedSession.id}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function chooseInitialChoice(choice: InitialChoice) {
  if (!session.value) return
  submitting.value = true
  errorMessage.value = ""
  const draftContent = currentStepContent.value
  try {
    session.value = await submitInitialChoice(sessionId, choice, session.value.version)
    if (session.value.flowStage === "CAPTURING_INPUT") {
      await loadCurrentSteps()
    }
  } catch (error) {
    if (isVersionConflict(error)) {
      await reloadAfterVersionConflict(draftContent)
    } else {
      errorMessage.value = error instanceof Error ? error.message : String(error)
    }
  } finally {
    submitting.value = false
  }
}

function hasStepEvidence() {
  return Boolean(currentStepContent.value.trim() || currentStepTranscript.value.trim())
}

function openFormulaEditor() {
  if (selfExplanationEditingDisabled.value || voiceRecording.value) return
  formulaEditorRef.value?.open()
}

async function ensureStepInputReady() {
  if (!session.value) return
  const draftBeforeTransition = currentStepContent.value
  let transitionedToStepInput = false
  if (session.value.flowStage === "WAIT_INITIAL_CHOICE") {
    session.value = await submitInitialChoice(sessionId, "KNOW", session.value.version)
    transitionedToStepInput = true
  } else if (session.value.flowStage === "WAIT_STUDENT_ACTION") {
    session.value = await continueExplaining(sessionId, session.value.version)
    transitionedToStepInput = true
  }
  if (transitionedToStepInput && session.value.flowStage === "CAPTURING_INPUT") {
    await loadCurrentSteps()
    currentStepContent.value = draftBeforeTransition
  }
}

async function submitExplanation() {
  if (!session.value || !canSubmitSelfExplanation.value) return
  if (voiceRecording.value) {
    stopVoiceRecorder(activeVoiceKey.value ?? "")
    return
  }
  submitting.value = true
  errorMessage.value = ""
  teacherReplyRequested.value = true
  streamSnapshot.value = null
  let draftContent = ""
  let request: ReturnType<typeof beginAIRequest> | undefined
  try {
    await ensureStepInputReady()
    draftContent = currentStepContent.value
    explanationSubmitting.value = true
    if (currentStepId.value === null || !hasStepEvidence()) {
      errorMessage.value = "关键步骤和讲解不能同时为空"
      return
    }
    request = beginAIRequest()
    lastSubmittedSelfExplanation.value = draftContent
    if (!grading.value) {
      awaitingFirstGrading.value = true
      const response = await submitGradedStepAttempt(sessionId, draftContent, session.value.version, request.runId, request.controller.signal)
      if (!isActiveAIRequest(request)) return
      session.value = response.session; grading.value = response.grading
    } else {
      const nextSession = await submitStepAttempt(sessionId, draftContent, session.value.version, request.runId, request.controller.signal)
      if (!isActiveAIRequest(request)) return
      session.value = nextSession
    }
    clearStepState()
    syncActiveSegmentWithStage()
    await refreshTimeline()
  } catch (error) {
    if (request && !isActiveAIRequest(request)) return
    explanationSubmitting.value = false
    if (isVersionConflict(error)) {
      await reloadAfterVersionConflict(currentStepContent.value)
    } else if (!(await handleAIRequestFailure(error, draftContent))) {
      errorMessage.value = error instanceof Error ? error.message : String(error)
    }
    if (error instanceof SessionApiError && error.code === "TEACHING_GENERATION_FAILED") {
      try {
        await loadSessionData()
      } catch (refreshError) {
        console.error("教学生成失败后刷新会话失败", refreshError)
      }
    }
  } finally {
    if (!request || isActiveAIRequest(request)) {
      awaitingFirstGrading.value = false
      teacherReplyRequested.value = false
      activeAiRequest.value = null
      explanationSubmitting.value = false
      submitting.value = false
    }
  }
}

async function prepareStepVoice() {
  stopTeacherSpeech()
  if (!session.value) return false
  submitting.value = true
  errorMessage.value = ""
  try {
    await ensureStepInputReady()
    return session.value.flowStage === "CAPTURING_INPUT" && currentStepId.value !== null
  } catch (error) {
    if (isVersionConflict(error)) {
      await reloadAfterVersionConflict(currentStepContent.value)
    } else {
      errorMessage.value = error instanceof Error ? error.message : String(error)
    }
    return false
  } finally {
    submitting.value = false
  }
}

async function prepareExplainVoice() {
  return prepareStepVoice()
}

function stopVoiceRecorder(voiceKey: string) {
  if (voiceKey === "step") {
    stepVoiceRecorderRef.value?.stop()
  } else if (voiceKey === "explain") {
    explainVoiceRecorderRef.value?.stop()
  } else if (voiceKey === "doubt") {
    doubtVoiceRecorderRef.value?.stop()
  } else if (voiceKey === "appeal") {
    appealVoiceRecorderRef.value?.stop()
  } else if (voiceKey.startsWith("guided-")) {
    guidedVoiceRecorderRefs.value.forEach((recorder) => recorder.stop())
  } else if (voiceKey.startsWith("mastery-")) {
    masteryVoiceRecorderRefs.value.forEach((recorder) => recorder.stop())
  }
}

function appendTranscript(currentText: string, transcript: string) {
  const trimmedCurrentText = currentText.trimEnd()
  return trimmedCurrentText ? `${trimmedCurrentText}\n${transcript}` : transcript
}

function appendGuidedTranscript(questionId: string, text: string) {
  guidedAnswerText.value[questionId] = appendTranscript(
    guidedAnswerText.value[questionId] ?? "",
    text,
  )
}

// 连接、录音和等待最终转写期间共用操作互斥，避免提前提交或启动第二段录音。
function handleVoiceBusyChange(voiceKey: string, busy: boolean) {
  if (busy) stopTeacherSpeech()
  if (busy && activeVoiceKey.value && activeVoiceKey.value !== voiceKey) {
    stopVoiceRecorder(activeVoiceKey.value)
  }
  voiceRecording.value = busy
  activeVoiceKey.value = busy ? voiceKey : (
    activeVoiceKey.value === voiceKey ? undefined : activeVoiceKey.value
  )
}

function voiceAttemptKey(target: VoiceInputTarget, targetId?: string) {
  return `${target}:${targetId ?? ""}`
}

function getVoiceAttemptId(target: VoiceInputTarget, targetId?: string) {
  return voiceAttemptIds.value[voiceAttemptKey(target, targetId)]
}

function clearVoiceAttemptId(target: VoiceInputTarget, targetId?: string) {
  delete voiceAttemptIds.value[voiceAttemptKey(target, targetId)]
}

async function handleVoiceCompleted(
  target: VoiceInputTarget,
  targetId: string | undefined,
  payload: { attemptId: number; version: number },
) {
  // 转写完成后先刷新服务端版本，再恢复提交与下一次录音。
  submitting.value = true
  if (target !== "SELF_EXPLANATION_STEP" && target !== "SELF_EXPLANATION_EXPLAIN") {
    voiceAttemptIds.value[voiceAttemptKey(target, targetId)] = payload.attemptId
  }
  try {
    const currentDraftBeforeRefresh = currentStepContent.value
    session.value = await fetchSession(sessionId)
    if (session.value.version < payload.version) {
      session.value = { ...session.value, version: payload.version }
    }
    if (session.value.flowStage === "CAPTURING_INPUT") {
      await loadCurrentSteps()
      if (currentStepId.value !== null) {
        currentStepContent.value = currentDraftBeforeRefresh
      }
    }
    syncActiveSegmentWithStage()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

onBeforeUnmount(() => {
  pageDetached = true
  const request = activeAiRequest.value
  aiRequestGeneration += 1
  activeAiRequest.value = null
  detachStreamListener?.()
  request?.controller.abort()
  doubtControllers.forEach((controller) => controller.abort())
  doubtControllers.clear()
  stopGradingPolling()
  stopTeacherSpeech()
  stepVoiceRecorderRef.value?.stop()
  explainVoiceRecorderRef.value?.stop()
  doubtVoiceRecorderRef.value?.stop()
  appealVoiceRecorderRef.value?.stop()
  guidedVoiceRecorderRefs.value.forEach((recorder) => recorder.stop())
  masteryVoiceRecorderRefs.value.forEach((recorder) => recorder.stop())
})

async function loadIndependentDoubts() {
  doubtHistoryError.value = ""
  try {
    const rows = await fetchIndependentDoubts(sessionId)
    if (pageDetached) return
    const localIds = new Set(independentDoubts.value.map((row) => row.runId))
    independentDoubts.value = [...rows.filter((row) => !localIds.has(row.runId)), ...independentDoubts.value]
    for (const row of rows) {
      if (row.status === "RUNNING" && !doubtControllers.has(row.runId)) void followIndependentDoubt(row.runId)
    }
  } catch (error) {
    doubtHistoryError.value = error instanceof Error ? error.message : String(error)
  }
}

async function followIndependentDoubt(runId: string) {
  const controller = new AbortController()
  doubtControllers.set(runId, controller)
  try {
    const result = await subscribeAIRun<{ content: string }>(sessionId, runId, {
      signal: controller.signal,
      onSnapshot(snapshot) {
        if (pageDetached || controller.signal.aborted || snapshot.runId !== runId) return
        const channel = snapshot.channels.INDEPENDENT_DOUBT
        doubtPreviews.value[runId] = snapshot.status === "RUNNING" && channel?.status !== "FAILED"
          ? channel?.fields.content ?? "" : ""
      },
    })
    if (pageDetached) return
    const row = independentDoubts.value.find((item) => item.runId === runId)
    if (row) { row.status = "SUCCEEDED"; row.result = result; row.error = null }
  } catch (error) {
    if (controller.signal.aborted || pageDetached) return
    const row = independentDoubts.value.find((item) => item.runId === runId)
    if (row) {
      row.status = error instanceof AIStreamError && error.code === "AI_RUN_CANCELLED" ? "CANCELLED" : "FAILED"
      row.error = { message: error instanceof Error ? error.message : String(error), code: error instanceof AIStreamError ? error.code ?? "" : "AI_SERVICE_UNAVAILABLE", status: error instanceof AIStreamError ? error.status : 503 }
    }
  } finally {
    delete doubtPreviews.value[runId]
    doubtControllers.delete(runId)
  }
}

async function submitDoubt(retryQuestion?: string) {
  if (!session.value) return
  const text = retryQuestion ?? doubtDraft.value
  if (!text.trim() || doubtSubmitting.value) return
  const runId = crypto.randomUUID()
  independentDoubts.value.push({ runId, status: "RUNNING", question: text, result: null, error: null })
  // 独立答疑不占用主流程请求，接收成功后才清空仍未编辑的原草稿。
  doubtSubmitting.value = true
  try {
    await startIndependentDoubt(sessionId, runId, text, currentStepContent.value || session.value.currentDraft)
    if (pageDetached) return
    if (retryQuestion === undefined && doubtDraft.value === text) doubtDraft.value = ""
    void followIndependentDoubt(runId)
  } catch (error) {
    if (pageDetached) return
    const row = independentDoubts.value.find((item) => item.runId === runId)
    if (row) {
      row.status = "FAILED"
      row.error = { message: error instanceof Error ? error.message : String(error), code: error instanceof SessionApiError ? error.code ?? "" : "", status: error instanceof SessionApiError ? error.status : 503 }
    }
  } finally {
    doubtSubmitting.value = false
  }
}

function guidedAnswerSubmitted(questionId: string) {
  return session.value?.latestSupport?.guidedAnswers?.some(
    (answer) => answer.questionId === questionId,
  ) ?? false
}

function masteryCheckCompleted() {
  return Boolean(session.value?.masteryCheck?.results?.length)
}

async function submitMasteryAnswers() {
  const masteryCheck = session.value?.masteryCheck
  if (!session.value || !masteryCheck || cancelling.value || voiceRecording.value) return
  const answers: GuidedAnswer[] = []
  for (const masteryQuestion of masteryCheck.questions) {
    const answer = masteryAnswerText.value[masteryQuestion.id]?.trim() ?? ""
    if (!answer) {
      errorMessage.value = "请先回答全部核验问题再提交"
      return
    }
    answers.push({ questionId: masteryQuestion.id, answer })
  }
  submitting.value = true
  errorMessage.value = ""
  const request = beginAIRequest()
  try {
    const nextSession = await submitMasteryCheckAnswers(sessionId, answers, session.value.version, request.runId, request.controller.signal)
    if (!isActiveAIRequest(request)) return
    session.value = nextSession
    syncActiveSegmentWithStage()
    await refreshTimeline()
  } catch (error) {
    if (!isActiveAIRequest(request)) return
    if (!(await handleAIRequestFailure(error))) {
      errorMessage.value = error instanceof Error ? error.message : String(error)
    }
  } finally {
    if (isActiveAIRequest(request)) { activeAiRequest.value = null; submitting.value = false }
  }
}

async function submitGuidedQuestionAnswer(questionId: string) {
  if (!session.value || !session.value.latestSupport?.guidedQuestions || cancelling.value) return
  const answer = guidedAnswerText.value[questionId]?.trim() ?? ""
  if (!answer) {
    errorMessage.value = "请先回答这个子问题"
    return
  }
  submitting.value = true
  errorMessage.value = ""
  const request = beginAIRequest()
  try {
    const voiceAttemptId = getVoiceAttemptId("GUIDED_ANSWER", questionId)
    const nextSession = await submitGuidedAnswers(
      sessionId,
      [{ questionId, answer }],
      session.value.version,
      voiceAttemptId,
      request.runId,
      request.controller.signal,
    )
    if (!isActiveAIRequest(request)) return
    session.value = nextSession
    clearVoiceAttemptId("GUIDED_ANSWER", questionId)
    syncActiveSegmentWithStage()
    await refreshTimeline()
  } catch (error) {
    if (!isActiveAIRequest(request)) return
    if (await handleAIRequestFailure(error)) {
      clearVoiceAttemptId("GUIDED_ANSWER", questionId)
    } else {
      errorMessage.value = error instanceof Error ? error.message : String(error)
    }
  } finally {
    if (isActiveAIRequest(request)) { activeAiRequest.value = null; submitting.value = false }
  }
}

async function appealEvaluation() {
  if (!session.value || !appealDraft.value.trim()) {
    errorMessage.value = "请填写不同意 AI 判断的理由"
    return
  }
  submitting.value = true
  errorMessage.value = ""
  const request = beginAIRequest()
  try {
    const voiceAttemptId = getVoiceAttemptId("APPEAL")
    const nextSession = await submitAppeal(
      sessionId,
      appealDraft.value,
      session.value.version,
      voiceAttemptId,
      request.runId,
      request.controller.signal,
    )
    if (!isActiveAIRequest(request)) return
    session.value = nextSession
    clearVoiceAttemptId("APPEAL")
    await refreshTimeline()
  } catch (error) {
    if (!isActiveAIRequest(request)) return
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    if (isActiveAIRequest(request)) { activeAiRequest.value = null; submitting.value = false }
  }
}

async function respondToSolution(understood: boolean) {
  if (!session.value || cancelling.value) return
  submitting.value = true
  errorMessage.value = ""
  const request = beginAIRequest()
  try {
    const nextSession = await submitSolutionUnderstanding(sessionId, understood, session.value.version, request.runId, request.controller.signal)
    if (!isActiveAIRequest(request)) return
    session.value = nextSession
    if (session.value.flowStage === "CAPTURING_INPUT") {
      await loadCurrentSteps()
    } else {
      clearStepState()
    }
    syncActiveSegmentWithStage()
    await refreshTimeline()
  } catch (error) {
    if (!isActiveAIRequest(request)) return
    if (!(await handleAIRequestFailure(error))) {
      errorMessage.value = error instanceof Error ? error.message : String(error)
    }
  } finally {
    if (isActiveAIRequest(request)) { activeAiRequest.value = null; submitting.value = false }
  }
}
</script>

<template>
  <main class="session-page" :aria-busy="loading || submitting || cancelling">
    <div class="session-shell">
      <Teleport to="#app-header-actions">
        <div v-if="session" class="page-actions" role="none">
          <button type="button" role="menuitem" data-testid="restart-self-explanation" :disabled="submitting" @click="restartSelfExplanation">重新自讲</button>
          <button type="button" role="menuitem" data-testid="session-history" @click="openHistoryDrawer">自讲历史</button>
          <RouterLink v-if="authUser?.role === 'TEACHER'" role="menuitem" :to="`/sessions/${session.id}/logs`">查看运行日志</RouterLink>
        </div>
      </Teleport>
      <el-drawer v-model="historyDrawerVisible" title="自讲历史" direction="rtl" size="360px">
        <el-skeleton v-if="historyLoading" :rows="5" animated />
        <el-alert v-else-if="historyError" :title="historyError" type="error" :closable="false" show-icon />
        <el-empty v-else-if="historyItems.length === 0" description="暂无自讲历史" />
        <div v-else class="history-list">
          <button
            v-for="item in historyItems"
            :key="item.id"
            type="button"
            class="history-item"
            :class="{ 'is-current': item.id === Number(sessionId) }"
            @click="selectHistoryItem(item)"
          >
            <span class="history-item-name">{{ item.name }}</span>
            <el-tag size="small" :type="historyStatusType(item.status)">{{ historyStatusLabels[item.status] }}</el-tag>
            <time :datetime="item.createdAt">{{ formatHistoryCreatedAt(item.createdAt) }}</time>
          </button>
        </div>
      </el-drawer>
      <div v-if="errorMessage" class="error-state" role="alert">
        <el-alert :title="errorMessage" type="error" :closable="false" show-icon />
        <el-button data-testid="continue-session" type="primary" @click="continueAfterError">继续自讲</el-button>
      </div>
      <el-skeleton v-if="loading" :rows="5" animated aria-label="正在加载会话" />
      <template v-else-if="session">
        <section v-if="question" class="question-content" aria-label="题目">
          <div data-testid="question-content" class="question-rich-text" v-html="sanitizeQuestionHtml(question.questionContent)" />
        </section>
        <FirstExplanationGrading :grading="grading" :retrying="gradingRetrying" :submission-text="firstGradingSubmissionText" :preview-fields="gradingPreviewFields" :stream-run-id="gradingStreamRunId" @close="gradingDismissed = true" @retry="retryGradingResult" @acknowledge="acknowledgeGradingResult" />
        <div v-if="cancellableRunId && !['selfExplain', 'guidedAnswers', 'masteryCheck', 'doubt'].includes(activeSegment)" class="actions cancel-run-actions">
          <el-button data-testid="cancel-current-run" type="danger" plain :loading="cancelling" @click="stopCurrentRun">中断生成</el-button>
        </div>
        <el-alert v-if="gradingPollError" :title="gradingPollError" type="error" :closable="false" show-icon />
        <section v-if="showTeacherReply" class="session-section feedback-section" data-testid="teacher-reply" aria-label="学习反馈">
          <TeacherReplyCard :pending="teacherReplyPending || !canShowTeachingContent" :blocks="teacherReplyBlocks">
            <template #controls>
              <span v-if="!teacherReplyPending && canShowTeachingContent && masteryCheckCompleted()" id="mastery-result-speech" class="speech-anchor" />
              <span v-else-if="!teacherReplyPending && canShowTeachingContent && nextStepText" id="next-step-speech" class="speech-anchor" />
            </template>
            <template v-if="!teacherReplyPending && canShowTeachingContent">
              <template v-if="session.flowStage === 'SHOWING_FULL_SOLUTION' && !isTerminalSession()">
                <h2 class="speech-content-heading"><span id="solution-speech" class="speech-anchor" />完整解析</h2>
                <div v-if="question?.fullSolution" class="question-rich-text" v-html="sanitizeQuestionHtml(question.fullSolution)" />
                <p>请确认你是否已经理解解析，确认后直接进入掌握度核验。</p>
                <div class="actions"><el-button data-testid="understood-solution" type="primary" :loading="submitting" :disabled="cancelling" @click="respondToSolution(true)">我会了，进入掌握度核验</el-button><el-button :loading="submitting" :disabled="cancelling" @click="respondToSolution(false)">仍然不会</el-button></div>
              </template>
              <div v-else-if="session.status === 'COMPLETED'" class="completion-state"><h2>本轮自讲已完成</h2><p>{{ session.masteryCheck?.outcome === 'COMPLETED' ? masteryOutcomeLabels.COMPLETED : '你已经正确、完整地讲清了这道题。' }}</p></div>
              <div v-else-if="session.status === 'NEEDS_REVIEW'" class="solution-state"><h2 class="speech-content-heading"><span v-if="speechIsSolution" id="solution-speech" class="speech-anchor" />本题已结束，仍有未解决问题</h2><p>{{ masteryOutcomeLabels.NEEDS_REVIEW }}</p><div v-if="question?.fullSolution" class="question-rich-text" v-html="sanitizeQuestionHtml(question.fullSolution)" /></div>
              <div v-else-if="session.status === 'STOPPED_LIMIT'" class="solution-state"><h2 class="speech-content-heading"><span v-if="speechIsSolution" id="solution-speech" class="speech-anchor" />已达到本轮支持上限</h2><div v-if="question?.fullSolution" class="question-rich-text" v-html="sanitizeQuestionHtml(question.fullSolution)" /></div>
              <div v-if="session.masteryCheck?.results?.length" class="mastery-check-state">
                <p v-for="item in session.masteryCheck.results" :key="item.questionId" class="mastery-result" :class="item.passed ? 'is-positive' : 'is-attention'">{{ item.basis }}</p>
              </div>
            </template>
          </TeacherReplyCard>
        </section>
        <div v-if="speechControlsTarget === '#latest-reply-speech'" class="speech-content-heading"><span id="latest-reply-speech" class="speech-anchor" /></div>
          <section class="session-section input-section" aria-label="当前输入与主操作">
            <el-segmented
              v-model="activeSegment"
              data-testid="dialog-segmented"
              :options="segmentOptions"
              block
              class="dialog-segmented"
              aria-label="选择学习操作"
            />
            <div class="dialog-panel">
              <div v-show="activeSegment === 'selfExplain'" class="dialog-pane">
                  <FormulaEditor
                    ref="formulaEditorRef"
                    v-model="currentStepContent"
                    :disabled="selfExplanationEditingDisabled || activeSegment !== 'selfExplain'"
                  />
                  <p class="recording-help">语音输入写入步骤；开始自讲录入讲解，暂停后可继续，提交时一并使用。</p>
                  <StudentInputActions
                    class="self-explain-actions"
                    submit-test-id="submit-explanation"
                    formula-test-id="insert-formula"
                    :submit-disabled="!canSubmitSelfExplanation || voiceRecording"
                    :formula-disabled="selfExplanationEditingDisabled || voiceRecording"
                    :loading="submitting"
                    @submit="submitExplanation"
                    @formula="openFormulaEditor"
                  >
                    <template #before>
                    <VoiceRecorder
                      ref="explainVoiceRecorderRef"
                      :session-id="sessionId"
                      :version="session.version"
                      target="SELF_EXPLANATION_EXPLAIN"
                      start-test-id="record-explain"
                      stop-test-id="stop-record-explain"
                      label="开始自讲"
                      stop-label="暂停自讲"
                      inline
                      :disabled="selfExplanationReadOnly || submitting
                        || teachingEvaluationPending
                        || (voiceRecording && activeVoiceKey !== 'explain')"
                      :prepare-start="prepareExplainVoice"
                      @completed="handleVoiceCompleted('SELF_EXPLANATION_EXPLAIN', undefined, $event)"
                      @busy-change="handleVoiceBusyChange('explain', $event)"
                      @error="errorMessage = $event"
                    />
                    </template>
                    <template #voice>
                    <VoiceRecorder
                      ref="stepVoiceRecorderRef"
                      :session-id="sessionId"
                      :version="session.version"
                      target="SELF_EXPLANATION_STEP"
                      start-test-id="record-step"
                      stop-test-id="stop-record-step"
                      label="语音输入"
                      icon-button
                      inline
                      :disabled="selfExplanationReadOnly || submitting
                        || teachingEvaluationPending
                        || (voiceRecording && activeVoiceKey !== 'step')"
                      :prepare-start="prepareStepVoice"
                      @final-transcript="currentStepContent = appendTranscript(currentStepContent, $event)"
                      @completed="handleVoiceCompleted('SELF_EXPLANATION_STEP', undefined, $event)"
                      @busy-change="handleVoiceBusyChange('step', $event)"
                      @error="errorMessage = $event"
                    />
                    </template>
                    <template #after>
                      <el-button v-if="cancellableRunId" data-testid="cancel-current-run" type="danger" plain :loading="cancelling" @click="stopCurrentRun">中断生成</el-button>
                      <span id="self-explain-speech-controls" class="speech-controls-target" />
                    </template>
                  </StudentInputActions>
              </div>
              <div v-show="activeSegment === 'guidedAnswers'" class="dialog-pane">
                <template v-if="showGuidedAnswers && session.latestSupport?.guidedQuestions?.length">
                  <div v-if="speechControlsTarget === '#guided-speech'" class="speech-content-heading"><span id="guided-speech" class="speech-anchor" /><span>子问题</span></div>
                  <div v-for="(item, index) in session.latestSupport.guidedQuestions" :key="item.id" class="guided-question">
                    <p>{{ item.question }}</p>
                    <FormulaEditor
                      :ref="(editor) => { if (editor) guidedFormulaEditorRefs[item.id] = editor as InstanceType<typeof FormulaEditor>; else delete guidedFormulaEditorRefs[item.id] }"
                      :model-value="guidedAnswerText[item.id] ?? ''"
                      :test-id="`guided-answer-${item.id}`"
                      :label="`回答子问题 ${index + 1}`"
                      placeholder="请输入你的回答"
                      :disabled="submitting || guidedAnswerSubmitted(item.id) || activeSegment !== 'guidedAnswers'"
                      @update:model-value="guidedAnswerText[item.id] = $event"
                    />
                    <StudentInputActions
                        :submit-test-id="`submit-guided-answer-${item.id}`"
                        :formula-test-id="`insert-formula-guided-${item.id}`"
                        :loading="submitting"
                        :submit-disabled="submitting || cancelling || runPending || guidedAnswerSubmitted(item.id)
                          || voiceRecording
                          || session.flowStage !== 'WAIT_GUIDED_ANSWERS'"
                        :formula-disabled="submitting || voiceRecording || guidedAnswerSubmitted(item.id)"
                        @submit="submitGuidedQuestionAnswer(item.id)"
                        @formula="guidedFormulaEditorRefs[item.id]?.open()"
                    >
                      <template #voice>
                      <VoiceRecorder
                        ref="guidedVoiceRecorderRefs"
                        :session-id="sessionId"
                        :version="session.version"
                        target="GUIDED_ANSWER"
                        :prepare-start="prepareReplyRecording"
                        :target-id="item.id"
                        :start-test-id="`start-voice-guided-${item.id}`"
                        :stop-test-id="`stop-voice-guided-${item.id}`"
                        label="语音输入"
                        icon-button
                        inline
                        :disabled="submitting
                          || guidedAnswerSubmitted(item.id)
                          || session.flowStage !== 'WAIT_GUIDED_ANSWERS'
                          || (voiceRecording && activeVoiceKey !== `guided-${item.id}`)"
                        @final-transcript="appendGuidedTranscript(item.id, $event)"
                        @completed="handleVoiceCompleted('GUIDED_ANSWER', item.id, $event)"
                        @busy-change="handleVoiceBusyChange(`guided-${item.id}`, $event)"
                        @error="errorMessage = $event"
                      />
                      </template>
                      <template #after>
                        <el-button v-if="cancellableRunId" data-testid="cancel-current-run" type="danger" plain :loading="cancelling" @click="stopCurrentRun">中断生成</el-button>
                        <span v-if="index === 0" id="guided-answer-speech-controls" class="speech-controls-target" />
                      </template>
                    </StudentInputActions>
                  </div>
                </template>
                <el-empty v-else description="暂无子问题" />
              </div>
              <div v-show="activeSegment === 'masteryCheck'" class="dialog-pane">
                <template v-if="canShowTeachingContent && session.masteryCheck?.questions?.length">
                  <div v-if="speechControlsTarget === '#mastery-speech'" class="speech-content-heading"><span id="mastery-speech" class="speech-anchor" /><span>掌握度核验</span></div>
                  <div v-for="(item, index) in session.masteryCheck.questions" :key="item.id" class="guided-question">
                    <FormulaEditor
                      :ref="(editor) => { if (editor) masteryFormulaEditorRefs[item.id] = editor as InstanceType<typeof FormulaEditor>; else delete masteryFormulaEditorRefs[item.id] }"
                      :model-value="masteryAnswerText[item.id] ?? ''"
                      :test-id="`mastery-answer-${item.id}`"
                      :label="`回答第 ${index + 1} 个核验问题`"
                      placeholder="请回答上方老师回复中的核验问题"
                      :disabled="submitting || masteryCheckCompleted() || activeSegment !== 'masteryCheck'"
                      @update:model-value="masteryAnswerText[item.id] = $event"
                    />
                    <StudentInputActions
                      class="mastery-check-actions"
                      :submit-test-id="index === 0 ? 'submit-mastery-check' : `submit-mastery-check-${item.id}`"
                      :formula-test-id="`insert-formula-mastery-${item.id}`"
                      :loading="submitting"
                      :submit-disabled="submitting || cancelling || runPending || voiceRecording || masteryCheckCompleted() || session.flowStage !== 'WAIT_MASTERY_CHECK'"
                      :formula-disabled="submitting || voiceRecording || masteryCheckCompleted()"
                      @submit="submitMasteryAnswers"
                      @formula="masteryFormulaEditorRefs[item.id]?.open()"
                    >
                      <template #voice>
                        <VoiceRecorder
                          ref="masteryVoiceRecorderRefs"
                          :session-id="sessionId"
                          :version="session.version"
                          target="MASTERY_ANSWER"
                          :target-id="item.id"
                          :prepare-start="prepareReplyRecording"
                          :start-test-id="`start-voice-mastery-${item.id}`"
                          :stop-test-id="`stop-voice-mastery-${item.id}`"
                          label="语音输入"
                          icon-button
                          inline
                          :disabled="submitting || cancelling || runPending || masteryCheckCompleted()
                            || session.flowStage !== 'WAIT_MASTERY_CHECK'
                            || (voiceRecording && activeVoiceKey !== `mastery-${item.id}`)"
                          @final-transcript="masteryAnswerText[item.id] = appendTranscript(masteryAnswerText[item.id] ?? '', $event)"
                          @completed="handleVoiceCompleted('MASTERY_ANSWER', item.id, $event)"
                          @busy-change="handleVoiceBusyChange(`mastery-${item.id}`, $event)"
                          @error="errorMessage = $event"
                        />
                      </template>
                      <template #after>
                        <el-button v-if="cancellableRunId" data-testid="cancel-current-run" type="danger" plain :loading="cancelling" @click="stopCurrentRun">中断生成</el-button>
                        <span v-if="index === 0" id="mastery-check-speech-controls" class="speech-controls-target" />
                      </template>
                    </StudentInputActions>
                  </div>
                </template>
                <el-empty v-else description="暂无核验问题" />
              </div>
              <div v-show="activeSegment === 'doubt'" class="dialog-pane">
                <FormulaEditor
                  ref="doubtFormulaEditorRef"
                  v-model="doubtDraft"
                  test-id="doubt-draft"
                  label="你的疑问"
                  placeholder="请输入你的疑问点"
                  :disabled="activeSegment !== 'doubt'"
                />
                <StudentInputActions
                    class="doubt-actions"
                    submit-test-id="submit-doubt"
                    formula-test-id="insert-formula-doubt"
                    :loading="doubtSubmitting"
                    :submit-disabled="!doubtDraft.trim() || doubtSubmitting || submitting || cancelling || voiceRecording"
                    :formula-disabled="voiceRecording"
                    @submit="submitDoubt()"
                    @formula="doubtFormulaEditorRef?.open()"
                >
                  <template #voice>
                  <VoiceRecorder
                    ref="doubtVoiceRecorderRef"
                    :session-id="sessionId"
                    :version="session.version"
                    target="DOUBT"
                    :prepare-start="prepareReplyRecording"
                    start-test-id="start-voice-doubt"
                    stop-test-id="stop-voice-doubt"
                    label="语音输入"
                    icon-button
                    inline
                    :disabled="submitting || !canSubmitStudentInterruption() || (voiceRecording && activeVoiceKey !== 'doubt')"
                    @final-transcript="doubtDraft = appendTranscript(doubtDraft, $event)"
                    @completed="handleVoiceCompleted('DOUBT', undefined, $event)"
                    @busy-change="handleVoiceBusyChange('doubt', $event)"
                    @error="errorMessage = $event"
                  />
                  </template>
                  <template #after>
                    <el-button v-if="cancellableRunId" data-testid="cancel-current-run" type="danger" plain :loading="cancelling" @click="stopCurrentRun">中断生成</el-button>
                    <span id="doubt-speech-controls" class="speech-controls-target" />
                  </template>
                </StudentInputActions>
                <div v-if="doubtHistoryError" class="actions" role="alert">
                  <span>{{ doubtHistoryError }}</span>
                  <el-button @click="loadIndependentDoubts">重新加载答疑记录</el-button>
                </div>
                <div v-if="independentDoubts.length" class="doubt-history" aria-label="答疑记录" aria-live="polite">
                  <article v-for="item in independentDoubts" :key="item.runId" class="doubt-thread" :data-testid="`doubt-${item.runId}`">
                    <p class="conversation-content"><strong>我的疑问：</strong><span v-html="renderStudentTextHtml(item.question)" /></p>
                    <TeacherReplyCard
                      :pending="item.status === 'RUNNING'"
                      :blocks="item.result ? [{ key: 'content', text: item.result.content }] : doubtPreviews[item.runId] ? [{ key: 'content', text: doubtPreviews[item.runId] }] : []"
                      :error="item.status === 'FAILED' || item.status === 'CANCELLED' ? (item.error?.code === 'AI_SERVICE_UNAVAILABLE' ? 'AI服务调用失败，请稍后再试' : item.error?.message || 'AI服务调用失败，请稍后再试') : undefined"
                    >
                      <el-button v-if="item.status === 'FAILED' || item.status === 'CANCELLED'" data-testid="retry-doubt" @click="submitDoubt(item.question)">重试发送</el-button>
                    </TeacherReplyCard>
                  </article>
                </div>
              </div>
              <div v-show="activeSegment === 'appeal'" class="dialog-pane">
                <el-input
                  v-model="appealDraft"
                  data-testid="appeal-draft"
                  type="textarea"
                  :rows="5"
                  placeholder="请填写你认为 AI 说错了的理由"
                  :disabled="submitting"
                />
                <div class="actions">
                  <el-button
                    data-testid="submit-appeal"
                    type="warning"
                    :loading="submitting"
                    :disabled="submitting
                      || voiceRecording
                      || !hasAppealableAiResponse()
                      || !canSubmitStudentInterruption()"
                    @click="appealEvaluation"
                  >
                    AI说错了
                  </el-button>
                  <VoiceRecorder
                    v-if="hasAppealableAiResponse()
                      && canSubmitStudentInterruption()"
                    ref="appealVoiceRecorderRef"
                    :session-id="sessionId"
                    :version="session.version"
                    target="APPEAL"
                    :prepare-start="prepareReplyRecording"
                    start-test-id="start-voice-appeal"
                    stop-test-id="stop-voice-appeal"
                    inline
                    :disabled="submitting || (voiceRecording && activeVoiceKey !== 'appeal')"
                    @final-transcript="appealDraft = appendTranscript(appealDraft, $event)"
                    @completed="handleVoiceCompleted('APPEAL', undefined, $event)"
                    @busy-change="handleVoiceBusyChange('appeal', $event)"
                    @error="errorMessage = $event"
                  />
                </div>
              </div>
            </div>
          </section>
        <section v-if="canShowTeachingContent && session.needHumanReason && session.status === 'IN_PROGRESS'" class="session-section"><el-alert title="已申请人工复核，你可以继续自讲。" type="warning" :closable="false" show-icon /></section>
        <TeacherSpeechPlayer
          v-if="canShowTeachingContent"
          ref="teacherSpeechRef"
          :session-id="sessionId"
          :item-ids="teacherReplyIds"
          :controls-target="speechControlsTarget"
          :full-solution="speechIsSolution"
          :disabled="submitting || voiceRecording"
        />
        <section class="session-section timeline-section" aria-labelledby="timeline-title">
          <h2 id="timeline-title">历史记录</h2>
          <el-empty v-if="!visibleTimeline.length" description="提交自讲后，学习记录会显示在这里" :image-size="72" />
          <el-scrollbar v-else class="conversation-scroll">
            <div class="conversation-list">
              <article
                v-for="item in visibleTimeline"
                :key="item.id"
                class="conversation-message"
                :class="timelineItemClass(item)"
                :aria-label="`${speakerLabels[item.speaker]}：${timelineTitle(item)}`"
              >
                <div class="conversation-meta">
                  <span class="conversation-speaker">{{ speakerLabels[item.speaker] }}</span>
                  <span class="conversation-event">{{ timelineTitle(item) }}</span>
                  <time>{{ new Date(item.createdAt).toLocaleString('zh-CN', { hour12: false }) }}</time>
                </div>
                <p
                  v-if="item.speaker === 'STUDENT' && ['SELF_EXPLANATION', 'GUIDED_ANSWER', 'MASTERY_ANSWER'].includes(item.submissionType ?? '')"
                  data-testid="timeline-content"
                  class="conversation-content"
                  v-html="renderStudentTextHtml(item.content)"
                />
                <p v-else data-testid="timeline-content" class="conversation-content">{{ item.content }}</p>
              </article>
            </div>
          </el-scrollbar>
        </section>
      </template>
    </div>
  </main>
</template>

<style scoped>
.session-page { max-width: 1040px; margin: 0 auto; padding: var(--space-6) var(--space-6) var(--space-12); }
.session-shell { min-width: 0; }
.page-actions { display: flex; flex-direction: column; }
.page-actions button, .page-actions a { display: flex; align-items: center; min-height: 44px; padding: var(--space-2) var(--space-4); border: 0; background: transparent; color: var(--color-text-primary); font: inherit; font-size: var(--font-size-sm); text-decoration: none; cursor: pointer; text-align: left; }
.page-actions button:hover:not(:disabled), .page-actions a:hover { background: var(--color-surface-muted); }
.page-actions button:disabled { opacity: .5; cursor: default; }
.page-actions button:focus-visible, .page-actions a:focus-visible { outline: 2px solid var(--color-brand-600); outline-offset: -2px; }
.actions { display: flex; align-items: center; gap: var(--space-2); }
.actions { flex-wrap: wrap; margin-top: var(--space-4); }
.history-list { display: flex; flex-direction: column; gap: var(--space-2); }
.history-item { display: grid; grid-template-columns: 1fr auto; gap: var(--space-2); width: 100%; padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); color: var(--color-text-primary); background: var(--color-surface); text-align: left; cursor: pointer; }
.history-item:hover, .history-item.is-current { border-color: var(--color-brand-600); background: var(--color-brand-50); }
.history-item-name { font-weight: 700; }
.history-item time { grid-column: 1 / -1; color: var(--color-text-muted); font-size: var(--font-size-sm); }
.error-state { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.error-state .el-alert { flex: 1; }
h2, h3 { margin: 0; line-height: 1.4; }
h2 { font-size: var(--font-size-lg); }
.question-content { padding: var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); box-shadow: var(--shadow-sm); }
.question-content .question-rich-text { margin-top: 0; }
.question-rich-text { max-width: var(--reading-width); margin-top: var(--space-3); color: var(--color-text-primary); font-size: var(--font-size-lg); font-weight: 600; line-height: 1.75; overflow-wrap: anywhere; }
.question-rich-text :deep(p) { margin: 0; }
.question-rich-text :deep(p + p) { margin-top: var(--space-3); }
.question-rich-text :deep(img) { display: block; max-width: 100%; height: auto; }
.session-section { margin-top: var(--space-8); }
.session-section p { color: var(--color-text-secondary); }
.input-section, .feedback-section { margin-top: var(--space-4); }
.dialog-segmented { --el-segmented-item-selected-bg-color: var(--color-brand-700); width: 100%; margin-top: 0; }
.dialog-segmented :deep(.el-segmented__item) { min-height: 44px; }
.dialog-panel {
  margin-top: var(--space-2);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}
.guided-question + .guided-question { margin-top: var(--space-4); }
.guided-question p { margin: 0 0 var(--space-2); color: var(--color-text-primary); font-weight: 600; }
.guided-question .voice-recorder { margin-top: 0; }
.doubt-history { display: grid; gap: var(--space-4); margin-top: var(--space-4); }
.doubt-thread { padding-top: var(--space-3); border-top: 1px solid var(--color-border); }
.mastery-result { margin: var(--space-2) 0 0; font-weight: 400; }
.mastery-result.is-positive { color: var(--color-success, #15803d); }
.mastery-result.is-attention { color: var(--color-warning, #b45309); }
.step-actions { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; margin-top: var(--space-4); }
.session-section .recording-help { margin: var(--space-2) 0 0; color: var(--color-text-muted); font-size: var(--font-size-sm); }
.step-content-input {
  display: block;
  box-sizing: border-box;
  width: 100%;
  min-height: 128px;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-primary);
  background: var(--color-surface);
  line-height: 1.7;
  resize: vertical;
}
.step-content-input:focus {
  border-color: var(--color-brand-600);
  outline: 3px solid var(--color-focus-ring);
  outline-offset: 2px;
}
.step-content-input:disabled { cursor: not-allowed; opacity: 0.65; }
:deep(.student-math-error) { color: var(--color-error-700); background: var(--color-error-100); text-decoration: underline wavy; }
.speech-content-heading { display: flex; align-items: flex-start; gap: var(--space-2); }
.speech-anchor { display: inline-flex; flex-shrink: 0; }
.speech-content-heading { align-items: center; margin-bottom: var(--space-3); font-weight: 600; }
.conversation-scroll {
  height: 480px;
  margin-top: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-muted);
}
.conversation-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
}
.conversation-message {
  max-width: min(680px, 88%);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface);
}
.conversation-message.is-student {
  align-self: flex-end;
  border-color: var(--color-student-border);
  background: var(--color-brand-50);
}
.conversation-message.is-ai {
  align-self: flex-start;
  border-color: var(--color-ai-border);
  background: var(--color-ai-surface);
}
.conversation-message.is-system {
  align-self: center;
  border-color: var(--color-system-border);
  background: var(--color-system-surface);
}
.conversation-meta {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-text-muted);
  font-size: 12px;
}
.conversation-speaker { display: inline-flex; min-height: 24px; align-items: center; padding: 0 var(--space-2); border: 1px solid currentColor; border-radius: 999px; color: var(--color-text-primary); font-weight: 700; }
.conversation-event { color: var(--color-text-primary); font-weight: 700; }
.conversation-meta time { margin-left: auto; }
.conversation-message.is-student .conversation-speaker { color: var(--color-brand-700); }
.conversation-message.is-ai .conversation-speaker { color: var(--color-success-700); }
.conversation-message.is-system .conversation-speaker { color: var(--color-action-700); }
.conversation-content {
  margin: var(--space-2) 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--color-text-primary);
}
.completion-state { color: var(--color-success-700); }
.solution-state p { max-width: var(--reading-width); white-space: pre-wrap; color: var(--color-text-primary); }
@media (max-width: 768px) {
  .dialog-segmented :deep(.el-segmented__group) { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); width: 100%; gap: var(--space-2); background: transparent; }
  /* Element Plus 在浮动选中层上设置内联 display，多行布局改由各选项绘制底色。 */
  .dialog-segmented :deep(.el-segmented__item-selected) { display: none !important; }
  .dialog-segmented :deep(.el-segmented__item) { min-width: 0; padding: var(--space-2); border-radius: var(--radius-md); white-space: normal; }
  .dialog-segmented :deep(.el-segmented__item.is-selected) { background: var(--color-brand-700); }
  .dialog-segmented :deep(.el-segmented__item.is-selected.is-disabled) { color: var(--color-text-secondary); background: var(--color-brand-100); }
  .dialog-segmented :deep(.el-segmented__item:has(input:focus-visible)) { outline: 2px solid var(--color-brand-700); outline-offset: 2px; }
}
@media (max-width: 640px) {
  .session-page { padding: var(--space-4) var(--space-4) var(--space-8); }
  .question-content { padding: var(--space-4); }
  .dialog-panel { padding: var(--space-4); }
  .actions .el-button { flex: 1 1 100%; }
  .step-actions .el-button { flex: 1 1 100%; }
  .conversation-scroll { height: 480px; }
  .conversation-list { padding: var(--space-3); }
  .conversation-message { width: 100%; max-width: none; }
  .conversation-meta { flex-wrap: wrap; gap: var(--space-2); }
  .conversation-meta time { width: 100%; margin-left: 0; }
}
@media (max-width: 560px) {
  .error-state { align-items: stretch; flex-direction: column; }
}
</style>
