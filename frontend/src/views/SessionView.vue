<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"

import {
  askDoubt,
  continueExplaining,
  createSession,
  fetchLearningTimeline,
  fetchSession,
  SessionApiError,
  submitAppeal,
  submitGuidedAnswers,
  submitInitialChoice,
  submitSolutionUnderstanding,
  submitTextAttempt,
} from "../api/sessions"
import VoiceRecorder from "../components/VoiceRecorder.vue"
import { fetchQuestion } from "../api/questions"
import { authUser } from "../stores/auth"
import type {
  AIEvaluation,
  InitialChoice,
  LearningTimelineItem,
  Session,
  VoiceInputTarget,
} from "../types/session"
import type { Question } from "../types/question"
import { sanitizeQuestionHtml } from "../utils/questionHtml"

type SegmentKey = "selfExplain" | "guidedAnswers" | "doubt" | "appeal"

interface DialogDrafts {
  selfExplain: string
  guidedAnswers: Record<string, string>
  doubt: string
  appeal: string
}

const route = useRoute()
const router = useRouter()
const session = ref<Session>()
const question = ref<Question>()
const timeline = ref<LearningTimelineItem[]>([])
const activeSegment = ref<SegmentKey>("selfExplain")
const selfExplainDraft = ref("")
const guidedAnswerText = ref<Record<string, string>>({})
const doubtDraft = ref("")
const appealDraft = ref("")
const loading = ref(true)
const submitting = ref(false)
const errorMessage = ref("")
const voiceRecording = ref(false)
const activeVoiceKey = ref<string>()
const voiceAttemptIds = ref<Record<string, number>>({})
const voiceRecorderRef = ref<InstanceType<typeof VoiceRecorder>>()
const doubtVoiceRecorderRef = ref<InstanceType<typeof VoiceRecorder>>()

const sessionId = String(route.params.sessionId)
const dialogDraftStorageKey = `ai-self-explain:session:${sessionId}:dialog-drafts`
let dialogDraftsReady = false

const segmentEntries: Array<{ label: string; value: SegmentKey }> = [
  { label: "自讲", value: "selfExplain" },
  { label: "回答子问题", value: "guidedAnswers" },
  { label: "我有疑问", value: "doubt" },
]

const studentInterruptionFlowStages = new Set<Session["flowStage"]>([
  "WAIT_INITIAL_CHOICE",
  "CAPTURING_INPUT",
  "WAIT_STUDENT_ACTION",
  "WAIT_GUIDED_ANSWERS",
  "SHOWING_FULL_SOLUTION",
])

const correctnessLabels: Record<AIEvaluation["correctness"], string> = {
  CORRECT: "正确",
  WRONG: "有错误",
}

const completenessLabels: Record<AIEvaluation["completeness"], string> = {
  COMPLETE: "完整",
  INCOMPLETE: "不完整",
}

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
}

function emptyDialogDrafts(): DialogDrafts {
  return {
    selfExplain: "",
    guidedAnswers: {},
    doubt: "",
    appeal: "",
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
        selfExplain: typeof parsed.selfExplain === "string" ? parsed.selfExplain : "",
        guidedAnswers: parsed.guidedAnswers && typeof parsed.guidedAnswers === "object"
          ? parsed.guidedAnswers
          : {},
        doubt: typeof parsed.doubt === "string" ? parsed.doubt : "",
        appeal: typeof parsed.appeal === "string" ? parsed.appeal : "",
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
      selfExplain: selfExplainDraft.value,
      guidedAnswers: guidedAnswerText.value,
      doubt: doubtDraft.value,
      appeal: appealDraft.value,
    }),
  )
}

function applyStoredDialogDrafts(currentDraft: string) {
  const savedDraftState = readDialogDrafts()
  selfExplainDraft.value = savedDraftState.hasStoredDrafts
    ? savedDraftState.drafts.selfExplain
    : currentDraft
  guidedAnswerText.value = savedDraftState.drafts.guidedAnswers
  doubtDraft.value = savedDraftState.drafts.doubt
  appealDraft.value = savedDraftState.drafts.appeal
  dialogDraftsReady = true
  persistDialogDrafts()
}

watch([selfExplainDraft, guidedAnswerText, doubtDraft, appealDraft], persistDialogDrafts, { deep: true })

async function loadSessionData() {
  const loadedSession = await fetchSession(sessionId)
  session.value = loadedSession
  if (!dialogDraftsReady) applyStoredDialogDrafts(loadedSession.currentDraft)
  for (const answer of loadedSession.latestSupport?.guidedAnswers ?? []) {
    if (!guidedAnswerText.value[answer.questionId]) {
      guidedAnswerText.value[answer.questionId] = answer.answer
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
  timeline.value = await fetchLearningTimeline(sessionId)
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
  if (segment === "doubt") return canSubmitStudentInterruption()
  return hasAppealableAiResponse() && canSubmitStudentInterruption()
}

const segmentOptions = computed(() => segmentEntries.map((segment) => ({
  ...segment,
  disabled: !canUseSegment(segment.value),
})))

const selfExplainCharacterCount = computed(() => selfExplainDraft.value.length)
const feedbackDetailsOpen = ref(false)

// const learningProgressSummary = computed(() => {
//   const rubricPoints = question.value?.rubricPoints ?? []
//   const rubricPointSet = new Set(rubricPoints)
//   const coveredPointCount = new Set(
//     (session.value?.coveredPointsCurrentRound ?? []).filter((point) => rubricPointSet.has(point)),
//   ).size
//   const remainingPointCount = Math.max(rubricPoints.length - coveredPointCount, 0)
//   return `已讲清 ${coveredPointCount} 个关键点，还差 ${remainingPointCount} 个`
// })

const coveredPointNumbers = computed(() => {
  return session.value?.latestEvaluation?.coveredPoints ?? []
})

const hasFollowUpContent = computed(
  () => Boolean(session.value?.latestSupport?.followUpContent),
)

const feedbackHeading = computed(() => {
  if (hasFollowUpContent.value && !session.value?.latestEvaluation) {
    return { title: "整合引导", description: "结合子问题答案，继续完成整道题的推理。" }
  }
  return { title: "最新反馈", description: "先看结论，再按需查看评价依据。" }
})

function evaluationClass(value: string) {
  if (value === "CORRECT" || value === "COMPLETE") return "is-positive"
  if (value === "WRONG") return "is-negative"
  return "is-attention"
}

function syncActiveSegmentWithStage() {
  if (session.value?.flowStage === "WAIT_GUIDED_ANSWERS") {
    activeSegment.value = "guidedAnswers"
  } else if (activeSegment.value === "guidedAnswers") {
    activeSegment.value = "selfExplain"
  }
}

function canSubmitStudentInterruption() {
  return session.value?.status === "IN_PROGRESS"
    && studentInterruptionFlowStages.has(session.value.flowStage)
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
  try {
    session.value = await submitInitialChoice(sessionId, choice, session.value.version)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function submitExplanation() {
  if (!session.value) return
  if (voiceRecording.value) {
    errorMessage.value = "请先结束录音后再提交自讲"
    return
  }
  if (!selfExplainDraft.value.trim()) {
    errorMessage.value = "请输入自讲内容后再提交"
    return
  }
  submitting.value = true
  errorMessage.value = ""
  try {
    if (session.value.flowStage === "WAIT_INITIAL_CHOICE") {
      session.value = await submitInitialChoice(sessionId, "KNOW", session.value.version)
    } else if (session.value.flowStage === "WAIT_STUDENT_ACTION") {
      session.value = await continueExplaining(sessionId, session.value.version)
    }
    const voiceAttemptId = getVoiceAttemptId("SELF_EXPLANATION")
    session.value = await submitTextAttempt(
      sessionId,
      selfExplainDraft.value,
      session.value.version,
      voiceAttemptId,
    )
    clearVoiceAttemptId("SELF_EXPLANATION")
    selfExplainDraft.value = session.value.currentDraft
    syncActiveSegmentWithStage()
    await refreshTimeline()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
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

async function prepareSelfExplanationVoiceInput() {
  if (!session.value) return
  submitting.value = true
  errorMessage.value = ""
  try {
    if (session.value.flowStage === "WAIT_INITIAL_CHOICE") {
      session.value = await submitInitialChoice(sessionId, "KNOW", session.value.version)
    } else if (session.value.flowStage === "WAIT_STUDENT_ACTION") {
      session.value = await continueExplaining(sessionId, session.value.version)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function startVoiceRecording() {
  if (!session.value || submitting.value) return
  if (session.value.flowStage === "WAIT_INITIAL_CHOICE" || session.value.flowStage === "WAIT_STUDENT_ACTION") {
    await prepareSelfExplanationVoiceInput()
    await nextTick()
  }
  if (session.value.flowStage !== "CAPTURING_INPUT") return
  await voiceRecorderRef.value?.start()
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

function appendFinalTranscript(text: string) {
  selfExplainDraft.value = appendTranscript(selfExplainDraft.value, text)
}

function appendGuidedTranscript(questionId: string, text: string) {
  guidedAnswerText.value[questionId] = appendTranscript(
    guidedAnswerText.value[questionId] ?? "",
    text,
  )
}

function handleRecordingChange(voiceKey: string, recording: boolean) {
  voiceRecording.value = recording
  activeVoiceKey.value = recording ? voiceKey : undefined
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
  attemptId: number,
) {
  voiceAttemptIds.value[voiceAttemptKey(target, targetId)] = attemptId
  try {
    session.value = await fetchSession(sessionId)
    syncActiveSegmentWithStage()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  }
}

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
      selfExplainDraft.value,
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
    selfExplainDraft.value = session.value.currentDraft
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
      <div class="page-header">
        <div><h1>自讲学习</h1><p>用自己的语言讲清思路，在反馈中逐步完善。</p></div>
        <div class="page-actions">
          <el-button v-if="session" data-testid="restart-self-explanation" :loading="submitting" @click="restartSelfExplanation">重新自讲</el-button>
          <RouterLink v-if="session && authUser?.role === 'TEACHER'" :to="`/sessions/${session.id}/logs`"><el-button>查看运行日志</el-button></RouterLink>
          <RouterLink v-if="session" to="/"><el-button>返回题目列表</el-button></RouterLink>
        </div>
      </div>
      <div v-if="errorMessage" class="error-state" role="alert">
        <el-alert :title="errorMessage" type="error" :closable="false" show-icon />
        <el-button data-testid="continue-session" type="primary" @click="continueAfterError">继续自讲</el-button>
      </div>
      <el-skeleton v-if="loading" :rows="5" animated aria-label="正在加载会话" />
      <template v-else-if="session">
        <section v-if="question" class="question-content" aria-labelledby="question-title">
          <h2 id="question-title">题目</h2>
          <div data-testid="question-content" class="question-rich-text" v-html="sanitizeQuestionHtml(question.questionContent)" />
        </section>
        <section v-if="session.latestEvaluation || hasFollowUpContent" class="session-section feedback-section" aria-labelledby="feedback-title" aria-live="polite">
          <div class="section-heading feedback-heading"><div><h2 id="feedback-title">{{ feedbackHeading.title }}</h2><p>{{ feedbackHeading.description }}</p></div></div>
          <div class="feedback-card">
            <template v-if="session.latestEvaluation">
            <div class="evaluation-results">
              <div class="evaluation-result" :class="evaluationClass(session.latestEvaluation.correctness)"><span>正确性</span><strong>{{ correctnessLabels[session.latestEvaluation.correctness] }}</strong></div>
              <div class="evaluation-result" :class="evaluationClass(session.latestEvaluation.completeness)"><span>完整性</span><strong>{{ completenessLabels[session.latestEvaluation.completeness] }}</strong></div>
            </div>
            <p v-if="coveredPointNumbers.length" class="covered-points">已覆盖评分点：{{ coveredPointNumbers.join('、') }}</p>
            </template>
            <p v-if="session.latestSupport?.content || hasFollowUpContent" class="feedback-next-step"><strong>下一步：</strong>{{ hasFollowUpContent ? session.latestSupport?.followUpContent : session.latestSupport?.content }}</p>
            <el-button
              v-if="session.latestEvaluation?.errorEvidence.length"
              class="feedback-toggle"
              text
              type="primary"
              :aria-expanded="feedbackDetailsOpen"
              aria-controls="feedback-details"
              @click="feedbackDetailsOpen = !feedbackDetailsOpen"
            >{{ feedbackDetailsOpen ? '收起评价依据' : '查看评价依据' }}</el-button>
            <div v-if="feedbackDetailsOpen && session.latestEvaluation?.errorEvidence.length" id="feedback-details" class="feedback-details">
              <article v-for="(evidence, index) in session.latestEvaluation.errorEvidence" :key="`${evidence.locationDescription}-${index}`" class="feedback-evidence">
                <h3>需要调整的地方</h3>
                <p><strong>你的表达：</strong>{{ evidence.quote }}</p>
                <p><strong>原因：</strong>{{ evidence.reason }}</p>
                <p><strong>思考方向：</strong>{{ evidence.thinkingDirection }}</p>
              </article>
            </div>
          </div>
        </section>
        <template v-if="session.status !== 'COMPLETED' && session.status !== 'STOPPED_LIMIT'">
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
                <el-input
                  v-model="selfExplainDraft"
                  data-testid="main-draft"
                  type="textarea"
                  :rows="5"
                  placeholder="输入题干理解、分析过程或完整自讲"
                  :disabled="submitting || session.flowStage === 'AI_EVALUATING'"
                  aria-label="自讲输入"
                  aria-describedby="self-explain-hint"
                />
                <div id="self-explain-hint" class="draft-meta"><span>已输入 {{ selfExplainCharacterCount }} 字</span><span>请用自己的语言说明思路。</span></div>
                <div
                  v-if="session.flowStage !== 'WAIT_GUIDED_ANSWERS'
                    && session.flowStage !== 'AI_EVALUATING'
                    && session.flowStage !== 'SHOWING_FULL_SOLUTION'"
                  class="actions self-explain-actions"
                >
                  <el-button
                      data-testid="submit-explanation"
                      type="primary"
                      :disabled="submitting || voiceRecording"
                      :loading="submitting"
                      @click="submitExplanation"
                    >提交</el-button>
                  <el-button
                    v-if="session.flowStage === 'WAIT_INITIAL_CHOICE'
                      || session.flowStage === 'WAIT_STUDENT_ACTION'"
                    data-testid="start-voice"
                    :disabled="voiceRecording"
                    @click="startVoiceRecording"
                  >录音</el-button>
                  <VoiceRecorder
                    v-if="session.flowStage === 'CAPTURING_INPUT' && !submitting"
                    ref="voiceRecorderRef"
                    :session-id="sessionId"
                    :version="session.version"
                    target="SELF_EXPLANATION"
                    inline
                    :disabled="submitting || (voiceRecording && activeVoiceKey !== 'self-explanation')"
                    @final-transcript="appendFinalTranscript"
                    @completed="handleVoiceCompleted('SELF_EXPLANATION', undefined, $event)"
                    @recording-change="handleRecordingChange('self-explanation', $event)"
                    @error="errorMessage = $event"
                  />
                </div>
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
                        :session-id="sessionId"
                        :version="session.version"
                        target="GUIDED_ANSWER"
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
                    :session-id="sessionId"
                    :version="session.version"
                    target="APPEAL"
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
          <section v-else-if="session.flowStage === 'SHOWING_FULL_SOLUTION'" class="session-section"><h2>完整解析</h2><div v-if="question?.fullSolution" class="question-rich-text" v-html="sanitizeQuestionHtml(question.fullSolution)" /><p>请确认你是否已经理解解析；确认后需要从头完成第二轮自讲。</p><div class="actions"><el-button data-testid="understood-solution" type="primary" :loading="submitting" @click="respondToSolution(true)">我会了，开始第二轮自讲</el-button><el-button :loading="submitting" @click="respondToSolution(false)">仍然不会</el-button></div></section>
        </template>
        <section v-if="session.needHumanReason && session.status === 'IN_PROGRESS'" class="session-section"><el-alert title="已申请人工复核，你可以继续自讲。" type="warning" :closable="false" show-icon /></section>
        <section v-if="session.status === 'COMPLETED'" class="session-section completion-state"><h2>本轮自讲已完成</h2><p>你已经正确、完整地讲清了这道题。</p></section>
        <section v-else-if="session.status === 'STOPPED_LIMIT'" class="session-section solution-state"><h2>已达到本轮支持上限</h2><div v-if="question?.fullSolution" class="question-rich-text" v-html="sanitizeQuestionHtml(question.fullSolution)" /></section>
        <section class="session-section timeline-section" aria-labelledby="timeline-title">
          <h2 id="timeline-title">历史记录</h2>
          <p class="section-description">按时间查看你的表达、AI 评价、提示与系统反馈。</p>
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
                <p v-if="item.correctness && item.completeness" class="timeline-evaluation">
                  正确性：{{ correctnessLabels[item.correctness] }}；完整性：{{ completenessLabels[item.completeness] }}
                </p>
                <p data-testid="timeline-content" class="conversation-content">{{ item.content }}</p>
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
.page-header, .page-actions, .actions { display: flex; align-items: center; gap: var(--space-2); }
.page-header { justify-content: space-between; margin-bottom: var(--space-6); }
.page-header p { margin: var(--space-2) 0 0; color: var(--color-text-secondary); }
.actions { flex-wrap: wrap; margin-top: var(--space-4); }
.error-state { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.error-state .el-alert { flex: 1; }
h1, h2, h3 { margin: 0; line-height: 1.4; }
h1 { font-size: var(--font-size-2xl); }
h2 { font-size: var(--font-size-lg); }
.question-content { padding: var(--space-6); border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); box-shadow: var(--shadow-sm); }
.question-rich-text { max-width: var(--reading-width); margin-top: var(--space-3); color: var(--color-text-primary); font-size: var(--font-size-lg); font-weight: 600; line-height: 1.75; overflow-wrap: anywhere; }
.question-rich-text :deep(p) { margin: 0; }
.question-rich-text :deep(p + p) { margin-top: var(--space-3); }
.question-rich-text :deep(img) { display: block; max-width: 100%; height: auto; }
.session-section { margin-top: var(--space-8); }
.session-section p { color: var(--color-text-secondary); }
.section-heading { display: flex; justify-content: space-between; gap: var(--space-4); }
.section-description, .section-heading p { margin: var(--space-1) 0 0; color: var(--color-text-muted); font-size: var(--font-size-sm); }
.evaluation-results { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
.evaluation-result { padding: var(--space-4); border-radius: var(--radius-md); background: var(--color-surface-muted); }
.evaluation-result span { display: block; color: var(--color-text-muted); font-size: var(--font-size-sm); }
.evaluation-result strong { display: block; margin-top: var(--space-1); font-size: var(--font-size-lg); }
.evaluation-result.is-positive { color: var(--color-success-700); background: var(--color-success-100); }
.evaluation-result.is-negative { color: var(--color-error-700); background: var(--color-error-100); }
.evaluation-result.is-attention { color: var(--color-action-700); background: var(--color-action-100); }
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
.draft-meta { display: flex; justify-content: space-between; gap: var(--space-3); margin-top: var(--space-2); color: var(--color-text-muted); font-size: var(--font-size-sm); }
.guided-question + .guided-question { margin-top: var(--space-4); }
.guided-question p { margin: 0 0 var(--space-2); color: var(--color-text-primary); font-weight: 600; }
.guided-question .voice-recorder { margin-top: 0; }
.feedback-card { margin-top: var(--space-4); padding: var(--space-5); border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); box-shadow: var(--shadow-sm); }
.feedback-next-step { margin: var(--space-4) 0 0; padding: var(--space-3); border-left: 3px solid var(--color-brand-600); border-radius: 0 var(--radius-sm) var(--radius-sm) 0; background: var(--color-brand-50); overflow-wrap: anywhere; }
.feedback-toggle { min-height: 44px; margin-top: var(--space-2); }
.feedback-details { display: grid; gap: var(--space-3); margin-top: var(--space-2); padding-top: var(--space-4); border-top: 1px solid var(--color-border); }
.feedback-evidence { padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-muted); }
.feedback-evidence h3 { font-size: var(--font-size-base); }
.feedback-evidence p { margin: var(--space-2) 0 0; overflow-wrap: anywhere; }
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
.timeline-evaluation { margin: var(--space-2) 0; color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.completion-state { color: var(--color-success-700); }
.solution-state p { max-width: var(--reading-width); white-space: pre-wrap; color: var(--color-text-primary); }
@media (max-width: 768px) {
  .dialog-segmented :deep(.el-segmented__group) { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); width: 100%; gap: var(--space-2); background: transparent; }
  .dialog-segmented :deep(.el-segmented__item) { min-width: 0; padding: var(--space-2); border-radius: var(--radius-md); white-space: normal; }
}
@media (max-width: 640px) {
  .session-page { padding: var(--space-6) var(--space-4) var(--space-8); }
  .page-header { align-items: flex-start; flex-direction: column; }
  .page-header a, .page-header .el-button { width: 100%; }
  .question-content { padding: var(--space-4); }
  .dialog-panel { padding: var(--space-4); }
  .draft-meta { align-items: flex-start; flex-direction: column; gap: 0; }
  .actions .el-button { flex: 1 1 100%; }
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
