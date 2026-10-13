<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"

import {
  askDoubt,
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
import {
  fetchSessionSteps,
  submitStepAttempt,
} from "../api/session-steps"
import FormulaEditor from "../components/FormulaEditor.vue"
import VoiceRecorder from "../components/VoiceRecorder.vue"
import TeacherSpeechPlayer from "../components/TeacherSpeechPlayer.vue"
import { fetchQuestion } from "../api/questions"
import { authUser } from "../stores/auth"
import type {
  GuidedAnswer,
  InitialChoice,
  LearningTimelineItem,
  Session,
  SessionHistoryItem,
  VoiceInputTarget,
} from "../types/session"
import type { StepsResponse } from "../types/session-step"
import type { Question } from "../types/question"
import { sanitizeQuestionHtml } from "../utils/questionHtml"
import { renderStudentTextHtml } from "../utils/studentTextHtml"

type SegmentKey = "selfExplain" | "guidedAnswers" | "masteryCheck" | "doubt" | "appeal"

interface DialogDrafts {
  guidedAnswers: Record<string, string>
  masteryCheck: Record<string, string>
  doubt: string
  appeal: string
  lastSubmittedSelfExplanation: string
}

const route = useRoute()
const router = useRouter()
const session = ref<Session>()
const question = ref<Question>()
const timeline = ref<LearningTimelineItem[]>([])
const activeSegment = ref<SegmentKey>("selfExplain")
const currentStepId = ref<number | null>(null)
const currentStepContent = ref("")
const currentStepTranscript = ref("")
// 上次成功提交时自讲框里的内容，用于在当前会话内回填，方便学生直接修改后重讲。
const lastSubmittedSelfExplanation = ref("")
const formulaEditorRef = ref<InstanceType<typeof FormulaEditor>>()
const guidedAnswerText = ref<Record<string, string>>({})
const masteryAnswerText = ref<Record<string, string>>({})
const doubtDraft = ref("")
const appealDraft = ref("")
const loading = ref(true)
const submitting = ref(false)
const errorMessage = ref("")
const voiceRecording = ref(false)
const activeVoiceKey = ref<string>()
const voiceAttemptIds = ref<Record<string, number>>({})
const doubtVoiceRecorderRef = ref<InstanceType<typeof VoiceRecorder>>()
const stepVoiceRecorderRef = ref<InstanceType<typeof VoiceRecorder>>()
const explainVoiceRecorderRef = ref<InstanceType<typeof VoiceRecorder>>()
const guidedVoiceRecorderRefs = ref<InstanceType<typeof VoiceRecorder>[]>([])
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
  return ["SUPPORT", "GUIDED_QUESTIONS", "FOLLOW_UP", "MASTERY_QUESTIONS"].includes(item.eventType)
}

// 手动播放定位最近一轮老师回复；初次加载历史只设置目标，不触发播放。
const teacherReplyIds = computed(() => {
  let lastReply = timeline.value.length - 1
  while (lastReply >= 0 && !isSpokenReply(timeline.value[lastReply])) lastReply -= 1
  if (lastReply < 0) return []
  let start = lastReply
  while (start > 0 && timeline.value[start - 1].speaker !== "STUDENT") start -= 1
  return timeline.value.slice(start, lastReply + 1).filter(isSpokenReply).map((item) => item.id)
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

watch(submitting, async (busy) => {
  if (busy) return
  const ids = pendingSpeechIds
  const generation = speechGeneration
  pendingSpeechIds = []
  if (!ids.length) return
  await nextTick()
  if (generation === speechGeneration && !submitting.value && !voiceRecording.value) {
    void teacherSpeechRef.value?.playReply(ids)
  }
}, { flush: "post" })

const sessionId = String(route.params.sessionId)
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
  dialogDraftsReady = true
  persistDialogDrafts()
}

watch(
  [guidedAnswerText, masteryAnswerText, doubtDraft, appealDraft, lastSubmittedSelfExplanation],
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

async function loadCurrentSteps() {
  if (!session.value || session.value.flowStage !== "CAPTURING_INPUT") return
  const response = await fetchSessionSteps(sessionId, "current")
  applyStepsResponse(response)
}

// 服务端已有步骤内容时以服务端为准，避免旧内容覆盖学生已保存的步骤。
function restoreLastSubmittedExplanation() {
  if (!currentStepContent.value.trim()) {
    currentStepContent.value = lastSubmittedSelfExplanation.value
  }
}

async function loadSessionData() {
  stopTeacherSpeech()
  const loadedSession = await fetchSession(sessionId)
  session.value = loadedSession
  if (!dialogDraftsReady) applyStoredDialogDrafts()
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
    await loadCurrentSteps()
    restoreLastSubmittedExplanation()
  } else {
    clearStepState()
    // 提交后会话停在 WAIT_STUDENT_ACTION 等阶段，服务端没有可读的当前步骤，
    // 刷新页面后用上次提交的内容回填；输入框已有内容时保留学生当前输入。
    if (!currentStepContent.value.trim()) {
      currentStepContent.value = lastSubmittedSelfExplanation.value
    }
  }
  syncActiveSegmentWithStage()
  const [loadedQuestion, loadedTimeline] = await Promise.all([
    fetchQuestion(String(loadedSession.questionId)),
    fetchLearningTimeline(sessionId),
  ])
  question.value = loadedQuestion
  timeline.value = loadedTimeline
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

onMounted(async () => {
  try {
    await loadSessionData()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
})

async function refreshTimeline() {
  const knownIds = new Set(timeline.value.map((item) => item.id))
  const refreshedTimeline = await fetchLearningTimeline(sessionId)
  timeline.value = refreshedTimeline
  const ids = refreshedTimeline.filter((item) => !knownIds.has(item.id) && isSpokenReply(item))
    .map((item) => item.id)
  if (submitting.value) {
    pendingSpeechIds = ids
  } else if (ids.length && !voiceRecording.value) {
    await nextTick()
    void teacherSpeechRef.value?.playReply(ids)
  }
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
  if (!session.value || submitting.value) return false
  if (segment === "selfExplain") {
    return ["WAIT_INITIAL_CHOICE", "CAPTURING_INPUT", "WAIT_STUDENT_ACTION"].includes(
      session.value.flowStage,
    )
  }
  if (segment === "guidedAnswers") return session.value.flowStage === "WAIT_GUIDED_ANSWERS"
  if (segment === "masteryCheck") return session.value.flowStage === "WAIT_MASTERY_CHECK"
  if (segment === "doubt") return canSubmitStudentInterruption()
  return hasAppealableAiResponse() && canSubmitStudentInterruption()
}

// 掌握度核验只在进入核验阶段后出现，其他阶段不提前暴露该入口。
const segmentOptions = computed(() => segmentEntries
  .filter((segment) => segment.value !== "masteryCheck"
    || session.value?.flowStage === "WAIT_MASTERY_CHECK")
  .map((segment) => ({
    ...segment,
    disabled: !canUseSegment(segment.value),
  })))

const hasFollowUpContent = computed(
  () => Boolean(session.value?.latestSupport?.followUpContent),
)

const feedbackHeading = computed(
  () => (hasFollowUpContent.value && !session.value?.latestEvaluation ? "整合引导" : "最新反馈"),
)

function syncActiveSegmentWithStage() {
  if (session.value?.flowStage === "WAIT_GUIDED_ANSWERS") {
    activeSegment.value = "guidedAnswers"
  } else if (session.value?.flowStage === "WAIT_MASTERY_CHECK") {
    activeSegment.value = "masteryCheck"
  } else if (activeSegment.value === "guidedAnswers" || activeSegment.value === "masteryCheck") {
    activeSegment.value = "selfExplain"
  }
}

function canSubmitStudentInterruption() {
  return session.value?.status === "IN_PROGRESS"
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
  if (submitting.value || voiceRecording.value) return
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
    if (draftBeforeTransition.trim()) {
      currentStepContent.value = draftBeforeTransition
    }
  }
}

async function submitExplanation() {
  if (!session.value) return
  if (voiceRecording.value) {
    stopVoiceRecorder(activeVoiceKey.value ?? "")
    return
  }
  submitting.value = true
  errorMessage.value = ""
  let draftContent = ""
  try {
    await ensureStepInputReady()
    draftContent = currentStepContent.value
    if (currentStepId.value === null || !hasStepEvidence()) {
      errorMessage.value = "关键步骤和讲解不能同时为空"
      return
    }
    session.value = await submitStepAttempt(
      sessionId,
      currentStepContent.value,
      session.value.version,
    )
    lastSubmittedSelfExplanation.value = draftContent
    clearStepState()
    syncActiveSegmentWithStage()
    await refreshTimeline()
  } catch (error) {
    if (isVersionConflict(error)) {
      await reloadAfterVersionConflict(draftContent)
    } else {
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
    submitting.value = false
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
  }
}

async function startDoubtVoiceRecording() {
  if (!session.value || submitting.value) return
  if (session.value.flowStage === "WAIT_INITIAL_CHOICE") {
    await chooseInitialChoice("HAS_QUESTION")
    await nextTick()
  }
  if (!canSubmitStudentInterruption()) return
  await doubtVoiceRecorderRef.value?.start()
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

function handleRecordingChange(voiceKey: string, recording: boolean) {
  if (recording) stopTeacherSpeech()
  if (recording && activeVoiceKey.value && activeVoiceKey.value !== voiceKey) {
    stopVoiceRecorder(activeVoiceKey.value)
  }
  voiceRecording.value = recording
  activeVoiceKey.value = recording ? voiceKey : (
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
  }
}

onBeforeUnmount(() => {
  stopTeacherSpeech()
  stepVoiceRecorderRef.value?.stop()
  explainVoiceRecorderRef.value?.stop()
  doubtVoiceRecorderRef.value?.stop()
  appealVoiceRecorderRef.value?.stop()
  guidedVoiceRecorderRefs.value.forEach((recorder) => recorder.stop())
})

async function submitDoubt() {
  if (!session.value) return
  if (!doubtDraft.value.trim()) {
    errorMessage.value = "请先输入你的疑问"
    return
  }
  submitting.value = true
  errorMessage.value = ""
  try {
    if (session.value.flowStage === "WAIT_INITIAL_CHOICE") {
      session.value = await submitInitialChoice(sessionId, "HAS_QUESTION", session.value.version)
    }
    const voiceAttemptId = getVoiceAttemptId("DOUBT")
    session.value = await askDoubt(
      sessionId,
      session.value.currentDraft,
      doubtDraft.value,
      session.value.version,
      voiceAttemptId,
    )
    clearVoiceAttemptId("DOUBT")
    syncActiveSegmentWithStage()
    await refreshTimeline()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
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

function masteryAnswerFor(questionId: string) {
  return session.value?.masteryCheck?.answers?.find(
    (answer) => answer.questionId === questionId,
  )?.answer
}

function masteryResultFor(questionId: string) {
  return session.value?.masteryCheck?.results?.find(
    (result) => result.questionId === questionId,
  )
}

async function submitMasteryAnswers() {
  const masteryCheck = session.value?.masteryCheck
  if (!session.value || !masteryCheck) return
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
  try {
    session.value = await submitMasteryCheckAnswers(sessionId, answers, session.value.version)
    syncActiveSegmentWithStage()
    await refreshTimeline()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function submitGuidedQuestionAnswer(questionId: string) {
  if (!session.value || !session.value.latestSupport?.guidedQuestions) return
  const answer = guidedAnswerText.value[questionId]?.trim() ?? ""
  if (!answer) {
    errorMessage.value = "请先回答这个子问题"
    return
  }
  submitting.value = true
  errorMessage.value = ""
  try {
    const voiceAttemptId = getVoiceAttemptId("GUIDED_ANSWER", questionId)
    session.value = await submitGuidedAnswers(
      sessionId,
      [{ questionId, answer }],
      session.value.version,
      voiceAttemptId,
    )
    clearVoiceAttemptId("GUIDED_ANSWER", questionId)
    syncActiveSegmentWithStage()
    await refreshTimeline()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function appealEvaluation() {
  if (!session.value || !appealDraft.value.trim()) {
    errorMessage.value = "请填写不同意 AI 判断的理由"
    return
  }
  submitting.value = true
  errorMessage.value = ""
  try {
    const voiceAttemptId = getVoiceAttemptId("APPEAL")
    session.value = await submitAppeal(
      sessionId,
      appealDraft.value,
      session.value.version,
      voiceAttemptId,
    )
    clearVoiceAttemptId("APPEAL")
    await refreshTimeline()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function respondToSolution(understood: boolean) {
  if (!session.value) return
  submitting.value = true
  errorMessage.value = ""
  try {
    session.value = await submitSolutionUnderstanding(sessionId, understood, session.value.version)
    if (session.value.flowStage === "CAPTURING_INPUT") {
      await loadCurrentSteps()
    } else {
      clearStepState()
    }
    syncActiveSegmentWithStage()
    await refreshTimeline()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="session-page" :aria-busy="loading || submitting">
    <div class="session-shell">
      <Teleport to="#app-header-actions">
        <div v-if="session" class="page-actions">
          <el-button data-testid="session-history" @click="openHistoryDrawer">自讲历史</el-button>
          <el-button data-testid="restart-self-explanation" :loading="submitting" @click="restartSelfExplanation">重新自讲</el-button>
          <RouterLink v-if="authUser?.role === 'TEACHER'" :to="`/sessions/${session.id}/logs`"><el-button>查看运行日志</el-button></RouterLink>
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
        <TeacherSpeechPlayer
          ref="teacherSpeechRef"
          :session-id="sessionId"
          :item-ids="teacherReplyIds"
          :disabled="submitting || voiceRecording"
        />
        <div v-if="session.solutionExposed && question?.fullSolution" class="actions">
          <el-button
            data-testid="play-full-solution"
            :disabled="submitting || voiceRecording"
            @click="teacherSpeechRef?.playSolution()"
          >播放完整解析</el-button>
        </div>
        <section v-if="question" class="question-content" aria-labelledby="question-title">
          <h2 id="question-title">题目</h2>
          <div data-testid="question-content" class="question-rich-text" v-html="sanitizeQuestionHtml(question.questionContent)" />
        </section>
        <section v-if="session.latestEvaluation || hasFollowUpContent" class="session-section feedback-section" aria-labelledby="feedback-title" aria-live="polite">
          <div class="section-heading feedback-heading"><div><h2 id="feedback-title">{{ feedbackHeading }}</h2></div></div>
          <div class="feedback-card">
            <p v-if="session.latestSupport?.content || hasFollowUpContent" class="feedback-next-step"><strong>下一步：</strong>{{ hasFollowUpContent ? session.latestSupport?.followUpContent : session.latestSupport?.content }}</p>
          </div>
        </section>
        <template v-if="!isTerminalSession()">
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
                <template v-if="session.flowStage === 'WAIT_INITIAL_CHOICE'
                  || session.flowStage === 'CAPTURING_INPUT'
                  || session.flowStage === 'WAIT_STUDENT_ACTION'">
                  <FormulaEditor
                    ref="formulaEditorRef"
                    v-model="currentStepContent"
                    :disabled="submitting || activeSegment !== 'selfExplain'"
                  />
                  <div class="step-actions self-explain-actions">
                    <el-button
                      data-testid="insert-formula"
                      :disabled="submitting || voiceRecording"
                      @click="openFormulaEditor"
                    >插入公式</el-button>
                    <el-button
                      data-testid="submit-explanation"
                      type="primary"
                      :disabled="submitting || voiceRecording"
                      :loading="submitting"
                      @click="submitExplanation"
                    >提交</el-button>
                    <VoiceRecorder
                      ref="explainVoiceRecorderRef"
                      :session-id="sessionId"
                      :version="session.version"
                      target="SELF_EXPLANATION_EXPLAIN"
                      start-test-id="record-explain"
                      stop-test-id="stop-record-explain"
                      label="讲解录音"
                      inline
                      :disabled="submitting
                        || (voiceRecording && activeVoiceKey !== 'explain')"
                      :prepare-start="prepareExplainVoice"
                      @completed="handleVoiceCompleted('SELF_EXPLANATION_EXPLAIN', undefined, $event)"
                      @recording-change="handleRecordingChange('explain', $event)"
                      @error="errorMessage = $event"
                    />
                    <VoiceRecorder
                      ref="stepVoiceRecorderRef"
                      :session-id="sessionId"
                      :version="session.version"
                      target="SELF_EXPLANATION_STEP"
                      start-test-id="record-step"
                      stop-test-id="stop-record-step"
                      label="步骤录音"
                      inline
                      :disabled="submitting
                        || (voiceRecording && activeVoiceKey !== 'step')"
                      :prepare-start="prepareStepVoice"
                      @final-transcript="currentStepContent = appendTranscript(currentStepContent, $event)"
                      @completed="handleVoiceCompleted('SELF_EXPLANATION_STEP', undefined, $event)"
                      @recording-change="handleRecordingChange('step', $event)"
                      @error="errorMessage = $event"
                    />
                  </div>
                </template>
                <el-empty v-else description="当前阶段暂无自讲输入" />
              </div>
              <div v-show="activeSegment === 'guidedAnswers'" class="dialog-pane">
                <template v-if="session.latestSupport?.guidedQuestions?.length">
                  <div v-for="item in session.latestSupport.guidedQuestions" :key="item.id" class="guided-question">
                    <p>{{ item.question }}</p>
                    <el-input
                      v-model="guidedAnswerText[item.id]"
                      :data-testid="`guided-answer-${item.id}`"
                      type="textarea"
                      :rows="5"
                      :disabled="submitting || guidedAnswerSubmitted(item.id)"
                    />
                    <div class="actions">
                      <el-button
                        :data-testid="`submit-guided-answer-${item.id}`"
                        type="primary"
                        :loading="submitting"
                        :disabled="guidedAnswerSubmitted(item.id)
                          || voiceRecording
                          || session.flowStage !== 'WAIT_GUIDED_ANSWERS'"
                        @click="submitGuidedQuestionAnswer(item.id)"
                      >提交</el-button>
                      <VoiceRecorder
                        v-if="session.flowStage === 'WAIT_GUIDED_ANSWERS' && !guidedAnswerSubmitted(item.id)"
                        ref="guidedVoiceRecorderRefs"
                        :session-id="sessionId"
                        :version="session.version"
                        target="GUIDED_ANSWER"
                        :prepare-start="prepareReplyRecording"
                        :target-id="item.id"
                        :start-test-id="`start-voice-guided-${item.id}`"
                        :stop-test-id="`stop-voice-guided-${item.id}`"
                        inline
                        :disabled="submitting
                          || guidedAnswerSubmitted(item.id)
                          || (voiceRecording && activeVoiceKey !== `guided-${item.id}`)"
                        @final-transcript="appendGuidedTranscript(item.id, $event)"
                        @completed="handleVoiceCompleted('GUIDED_ANSWER', item.id, $event)"
                        @recording-change="handleRecordingChange(`guided-${item.id}`, $event)"
                        @error="errorMessage = $event"
                      />
                    </div>
                  </div>
                </template>
                <el-empty v-else description="暂无子问题" />
              </div>
              <div v-show="activeSegment === 'masteryCheck'" class="dialog-pane">
                <template v-if="session.masteryCheck?.questions?.length">
                  <p class="mastery-check-hint">本题不支持重新完整自讲。请回答下面的核验问题，确认你是否真的掌握。</p>
                  <div v-for="item in session.masteryCheck.questions" :key="item.id" class="guided-question">
                    <p>{{ item.question }}</p>
                    <el-input
                      v-model="masteryAnswerText[item.id]"
                      :data-testid="`mastery-answer-${item.id}`"
                      type="textarea"
                      :rows="5"
                      :disabled="submitting || masteryCheckCompleted()"
                    />
                  </div>
                  <div class="actions">
                    <el-button
                      data-testid="submit-mastery-check"
                      type="primary"
                      :loading="submitting"
                      :disabled="submitting || masteryCheckCompleted() || session.flowStage !== 'WAIT_MASTERY_CHECK'"
                      @click="submitMasteryAnswers"
                    >提交核验回答</el-button>
                  </div>
                </template>
                <el-empty v-else description="暂无核验问题" />
              </div>
              <div v-show="activeSegment === 'doubt'" class="dialog-pane">
                <el-input
                  v-model="doubtDraft"
                  data-testid="doubt-draft"
                  type="textarea"
                  :rows="5"
                  placeholder="请输入你的疑问点"
                  :disabled="submitting"
                />
                <div class="actions">
                    <el-button
                      data-testid="submit-doubt"
                      type="primary"
                      :loading="submitting"
                      :disabled="submitting || voiceRecording || !canSubmitStudentInterruption()"
                      @click="submitDoubt"
                    >提交</el-button>
                  <VoiceRecorder
                    v-if="canSubmitStudentInterruption()"
                    ref="doubtVoiceRecorderRef"
                    :session-id="sessionId"
                    :version="session.version"
                    target="DOUBT"
                    :prepare-start="prepareReplyRecording"
                    start-test-id="start-voice-doubt"
                    stop-test-id="stop-voice-doubt"
                    inline
                    :disabled="submitting || (voiceRecording && activeVoiceKey !== 'doubt')"
                    @final-transcript="doubtDraft = appendTranscript(doubtDraft, $event)"
                    @completed="handleVoiceCompleted('DOUBT', undefined, $event)"
                    @recording-change="handleRecordingChange('doubt', $event)"
                    @error="errorMessage = $event"
                  />
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
                    @recording-change="handleRecordingChange('appeal', $event)"
                    @error="errorMessage = $event"
                  />
                </div>
              </div>
            </div>
          </section>
          <section v-if="session.flowStage === 'AI_EVALUATING'" class="session-section"><h2>AI 正在评价</h2><p>请等待评价结果返回。</p></section>
          <section v-else-if="session.flowStage === 'SHOWING_FULL_SOLUTION'" class="session-section"><h2>完整解析</h2><div v-if="question?.fullSolution" class="question-rich-text" v-html="sanitizeQuestionHtml(question.fullSolution)" /><p>请确认你是否已经理解解析。本题不会再要求完整重讲，确认后直接进入掌握度核验。</p><div class="actions"><el-button data-testid="understood-solution" type="primary" :loading="submitting" @click="respondToSolution(true)">我会了，进入掌握度核验</el-button><el-button :loading="submitting" @click="respondToSolution(false)">仍然不会</el-button></div></section>
          <section v-else-if="session.flowStage === 'WAIT_MASTERY_CHECK'" class="session-section mastery-check-state">
            <h2>掌握度核验</h2>
            <p class="mastery-check-note">请到上方「掌握度核验」中回答下面的问题；全部通过即完成本题。</p>
          </section>
        </template>
        <section v-if="session.needHumanReason && session.status === 'IN_PROGRESS'" class="session-section"><el-alert title="已申请人工复核，你可以继续自讲。" type="warning" :closable="false" show-icon /></section>
        <section v-if="session.status === 'COMPLETED'" class="session-section completion-state"><h2>本轮自讲已完成</h2><p>{{ session.masteryCheck?.outcome === 'COMPLETED' ? masteryOutcomeLabels.COMPLETED : '你已经正确、完整地讲清了这道题。' }}</p></section>
        <section v-else-if="session.status === 'NEEDS_REVIEW'" class="session-section solution-state"><h2>本题已结束，仍有未解决问题</h2><p>{{ masteryOutcomeLabels.NEEDS_REVIEW }}</p><div v-if="question?.fullSolution" class="question-rich-text" v-html="sanitizeQuestionHtml(question.fullSolution)" /></section>
        <section v-else-if="session.status === 'STOPPED_LIMIT'" class="session-section solution-state"><h2>已达到本轮支持上限</h2><div v-if="question?.fullSolution" class="question-rich-text" v-html="sanitizeQuestionHtml(question.fullSolution)" /></section>
        <section v-if="session.masteryCheck?.results?.length" class="session-section mastery-check-state">
          <h2>掌握度核验结论</h2>
          <div v-for="item in session.masteryCheck.questions" :key="item.id" class="guided-question">
            <p>{{ item.question }}</p>
            <p class="mastery-answer">你的回答：{{ masteryAnswerFor(item.id) ?? "未作答" }}</p>
            <p
              class="mastery-result"
              :class="masteryResultFor(item.id)?.passed ? 'is-positive' : 'is-attention'"
            >
              {{ masteryResultFor(item.id)?.passed ? "通过" : "未通过" }}：{{ masteryResultFor(item.id)?.basis }}
            </p>
          </div>
        </section>
        <section class="session-section timeline-section" aria-labelledby="timeline-title">
          <h2 id="timeline-title">历史记录</h2>
          <el-empty v-if="!timeline.length" description="提交自讲后，学习记录会显示在这里" :image-size="72" />
          <el-scrollbar v-else class="conversation-scroll">
            <div class="conversation-list">
              <article
                v-for="item in timeline"
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
                  v-if="item.speaker === 'STUDENT' && item.submissionType === 'SELF_EXPLANATION'"
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
.session-page { max-width: 1040px; margin: 0 auto; padding: var(--space-8) var(--space-6) var(--space-12); }
.session-shell { min-width: 0; }
.page-actions, .actions { display: flex; align-items: center; gap: var(--space-2); }
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
.question-content { padding: var(--space-6); border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); box-shadow: var(--shadow-sm); }
.question-rich-text { max-width: var(--reading-width); margin-top: var(--space-3); color: var(--color-text-primary); font-size: var(--font-size-lg); font-weight: 600; line-height: 1.75; overflow-wrap: anywhere; }
.question-rich-text :deep(p) { margin: 0; }
.question-rich-text :deep(p + p) { margin-top: var(--space-3); }
.question-rich-text :deep(img) { display: block; max-width: 100%; height: auto; }
.session-section { margin-top: var(--space-8); }
.session-section p { color: var(--color-text-secondary); }
.section-heading { display: flex; justify-content: space-between; gap: var(--space-4); }
.dialog-segmented { width: 100%; margin-top: var(--space-4); }
.dialog-segmented :deep(.el-segmented__item) { min-height: 44px; }
.dialog-panel {
  margin-top: var(--space-2);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  background: var(--color-surface);
  box-shadow: var(--shadow-md);
}
.dialog-pane { min-height: 190px; }
.guided-question + .guided-question { margin-top: var(--space-4); }
.guided-question p { margin: 0 0 var(--space-2); color: var(--color-text-primary); font-weight: 600; }
.guided-question .voice-recorder { margin-top: 0; }
.mastery-check-hint { margin: 0 0 var(--space-4); color: var(--color-text-secondary); font-weight: 400; }
.mastery-answer { margin: 0 0 var(--space-2); color: var(--color-text-secondary); font-weight: 400; }
.mastery-result { margin: var(--space-2) 0 0; font-weight: 400; }
.mastery-result.is-positive { color: var(--color-success, #15803d); }
.mastery-result.is-attention { color: var(--color-warning, #b45309); }
.mastery-check-note { margin: var(--space-2) 0 0; color: var(--color-text-secondary); }
.step-actions { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; margin-top: var(--space-4); }
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
.feedback-card { margin-top: var(--space-4); padding: var(--space-5); border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); box-shadow: var(--shadow-sm); }
.feedback-next-step { margin: var(--space-4) 0 0; padding: var(--space-3); border-left: 3px solid var(--color-brand-600); border-radius: 0 var(--radius-sm) var(--radius-sm) 0; background: var(--color-brand-50); overflow-wrap: anywhere; }
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
  .dialog-segmented :deep(.el-segmented__item) { min-width: 0; padding: var(--space-2); border-radius: var(--radius-md); white-space: normal; }
}
@media (max-width: 640px) {
  .session-page { padding: var(--space-6) var(--space-4) var(--space-8); }
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
