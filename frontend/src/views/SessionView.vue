<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue"
import { useRoute } from "vue-router"

import {
  askDoubt,
  continueExplaining,
  fetchLearningTimeline,
  fetchSession,
  requestSupport,
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
  SessionStatus,
  VoiceInputTarget,
} from "../types/session"
import type { Question } from "../types/question"

type SegmentKey = "selfExplain" | "guidedAnswers" | "doubt" | "appeal"

interface DialogDrafts {
  selfExplain: string
  guidedAnswers: Record<string, string>
  doubt: string
  appeal: string
}

const route = useRoute()
const session = ref<Session>()
const question = ref<Question>()
const timeline = ref<LearningTimelineItem[]>([])
const activeSegment = ref<SegmentKey>("selfExplain")
const selfExplainDraft = ref("")
const guidedAnswerText = ref<Record<string, string>>({})
const doubtDraft = ref("")
const appealDraft = ref("")
const emptyDraftReminderShown = ref(false)
const unchangedDraftReminderShown = ref(false)
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

const segmentOptions: Array<{ label: string; value: SegmentKey }> = [
  { label: "自讲", value: "selfExplain" },
  { label: "回答子问题", value: "guidedAnswers" },
  { label: "我有疑问", value: "doubt" },
  { label: "AI说错了", value: "appeal" },
]

const studentInterruptionFlowStages = new Set<Session["flowStage"]>([
  "WAIT_INITIAL_CHOICE",
  "CAPTURING_INPUT",
  "WAIT_STUDENT_ACTION",
  "WAIT_GUIDED_ANSWERS",
  "SHOWING_FULL_SOLUTION",
])

const sessionStatusLabels: Record<SessionStatus, string> = {
  IN_PROGRESS: "进行中",
  COMPLETED: "已完成",
  STOPPED_LIMIT: "已达到支持上限",
  NEED_HUMAN: "已申请人工复核",
  PAUSED: "已暂停",
}

const correctnessLabels: Record<AIEvaluation["correctness"], string> = {
  CORRECT: "正确",
  WRONG: "有错误",
  UNCERTAIN: "暂无法可靠判断",
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
  NEED_HUMAN: "已申请人工复核",
}

const timelineEventLabels: Record<LearningTimelineItem["eventType"], string> = {
  SUBMISSION: "学生提交",
  EVALUATION: "学习反馈",
  SUPPORT: "学习支持",
  FULL_SOLUTION: "完整解析",
  NEED_HUMAN: "人工复核已申请",
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

function sessionStatusType(status: SessionStatus) {
  if (status === "COMPLETED") return "success"
  if (status === "NEED_HUMAN") return "danger"
  if (status === "STOPPED_LIMIT" || status === "PAUSED") return "warning"
  return "primary"
}

function evaluationClass(value: string) {
  if (value === "CORRECT" || value === "COMPLETE") return "is-positive"
  if (value === "WRONG") return "is-negative"
  return "is-attention"
}

function syncActiveSegmentWithStage() {
  if (session.value?.flowStage === "WAIT_GUIDED_ANSWERS") {
    activeSegment.value = "guidedAnswers"
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

function resetDraftReminderIfChanged() {
  if (session.value && selfExplainDraft.value !== session.value.currentDraft) {
    unchangedDraftReminderShown.value = false
  }
}

function canRequestSupport() {
  resetDraftReminderIfChanged()
  if (!selfExplainDraft.value.trim() && !emptyDraftReminderShown.value) {
    emptyDraftReminderShown.value = true
    errorMessage.value = "请先输入当前的题干理解或者解题、分析过程；再次点击可继续。"
    return false
  }
  if (
    session.value?.flowStage === "WAIT_STUDENT_ACTION"
    && selfExplainDraft.value === session.value.currentDraft
    && !unchangedDraftReminderShown.value
  ) {
    unchangedDraftReminderShown.value = true
    errorMessage.value = "请先将刚才的思路补充到主输入框后再提交；再次点击可继续。"
    return false
  }
  return true
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

async function requestGuidedSupport() {
  if (!session.value || !canRequestSupport()) return
  submitting.value = true
  errorMessage.value = ""
  try {
    if (session.value.flowStage === "WAIT_INITIAL_CHOICE") {
      session.value = await submitInitialChoice(sessionId, "NOT_KNOW", session.value.version)
    }
    session.value = await requestSupport(sessionId, selfExplainDraft.value, session.value.version)
    syncActiveSegmentWithStage()
    await refreshTimeline()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
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
  <main class="session-page">
    <div class="session-shell">
      <div class="page-header">
        <div><h1>自讲学习</h1><p>用自己的语言讲清思路，在反馈中逐步完善。</p></div>
        <div class="page-actions">
          <RouterLink v-if="session && authUser?.role === 'TEACHER'" :to="`/sessions/${session.id}/logs`"><el-button>查看运行日志</el-button></RouterLink>
          <RouterLink v-if="session" to="/"><el-button>返回题目列表</el-button></RouterLink>
        </div>
      </div>
      <div v-if="errorMessage" class="error-state">
        <el-alert :title="errorMessage" type="error" :closable="false" show-icon />
        <el-button data-testid="continue-session" type="primary" @click="continueAfterError">继续自讲</el-button>
      </div>
      <el-skeleton v-if="loading" :rows="5" animated />
      <template v-else-if="session">
        <section v-if="question" class="question-content"><h2>题目</h2><p data-testid="question-content">{{ question.questionContent }}</p></section>
        <div class="session-summary" aria-label="学习进度">
          <div class="summary-item status-item"><span>会话状态</span><el-tag :type="sessionStatusType(session.status)" effect="light">{{ sessionStatusLabels[session.status] }}</el-tag></div>
          <div class="summary-item"><span>当前轮次</span><strong>第 {{ session.round }} 轮</strong></div>
          <div class="summary-item"><span>本轮支持</span><strong>{{ session.supportCountRound }} 次</strong></div>
          <div class="summary-item"><span>累计支持</span><strong>{{ session.supportCountTotal }} 次</strong></div>
        </div>
        <section v-if="session.latestEvaluation" class="session-section evaluation-section">
          <div><h2>本次自讲评价</h2><p>AI 从表达是否正确、是否完整两个方面给出结果。</p></div>
          <div class="evaluation-results">
            <div class="evaluation-result" :class="evaluationClass(session.latestEvaluation.correctness)"><span>正确性</span><strong>{{ correctnessLabels[session.latestEvaluation.correctness] }}</strong></div>
            <div class="evaluation-result" :class="evaluationClass(session.latestEvaluation.completeness)"><span>完整性</span><strong>{{ completenessLabels[session.latestEvaluation.completeness] }}</strong></div>
          </div>
        </section>
        <section class="session-section timeline-section">
          <h2>自讲记录</h2>
          <p class="section-description">按时间查看你的表达、AI 评价、提示与系统反馈。</p>
          <el-empty v-if="!timeline.length" description="提交自讲后，学习记录会显示在这里" :image-size="72" />
          <el-scrollbar v-else class="conversation-scroll">
            <div class="conversation-list">
              <article
                v-for="item in timeline"
                :key="item.id"
                class="conversation-message"
                :class="timelineItemClass(item)"
              >
                <div class="conversation-meta">
                  <span>{{ timelineTitle(item) }}</span>
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
        <section v-if="session.needHumanReason && session.status === 'IN_PROGRESS'" class="session-section"><el-alert title="已申请人工复核，你可以继续自讲。" type="warning" :closable="false" show-icon /></section>
        <section v-if="session.status === 'NEED_HUMAN'" class="session-section"><h2>需要人工处理</h2><el-alert title="自动学习流程已停止" :description="session.needHumanReason || '暂无法可靠判断，已转人工帮助。'" type="error" :closable="false" show-icon /></section>
        <section v-else-if="session.status === 'COMPLETED'" class="session-section completion-state"><h2>本轮自讲已完成</h2><p>你已经正确、完整地讲清了这道题。</p></section>
        <section v-else-if="session.status === 'STOPPED_LIMIT'" class="session-section solution-state"><h2>已达到本轮支持上限</h2><p v-if="question">{{ question.fullSolution }}</p></section>
        <template v-else>
          <section class="session-section">
            <div class="section-heading"><div><h2>开始表达</h2><p>内容会自动保存在当前浏览器中。</p></div></div>
            <el-segmented
              v-model="activeSegment"
              data-testid="dialog-segmented"
              :options="segmentOptions"
              block
              class="dialog-segmented"
            />
            <div class="dialog-panel">
              <div v-show="activeSegment === 'selfExplain'" class="dialog-pane">
                <el-input
                  v-model="selfExplainDraft"
                  data-testid="main-draft"
                  type="textarea"
                  :rows="8"
                  placeholder="输入题干理解、分析过程或完整自讲"
                  :disabled="submitting || session.flowStage === 'AI_EVALUATING'"
                />
                <VoiceRecorder
                  v-if="session.flowStage === 'CAPTURING_INPUT'"
                  ref="voiceRecorderRef"
                  :session-id="sessionId"
                  :version="session.version"
                  target="SELF_EXPLANATION"
                  :disabled="submitting || (voiceRecording && activeVoiceKey !== 'self-explanation')"
                  @final-transcript="appendFinalTranscript"
                  @completed="handleVoiceCompleted('SELF_EXPLANATION', undefined, $event)"
                  @recording-change="handleRecordingChange('self-explanation', $event)"
                  @error="errorMessage = $event"
                />
                <div
                  v-if="session.flowStage !== 'WAIT_GUIDED_ANSWERS'
                    && session.flowStage !== 'AI_EVALUATING'
                    && session.flowStage !== 'SHOWING_FULL_SOLUTION'"
                  class="actions"
                >
                  <el-button data-testid="submit-explanation" type="primary" :loading="submitting" @click="submitExplanation">提交自讲</el-button>
                  <el-button
                    v-if="session.flowStage === 'WAIT_INITIAL_CHOICE'
                      || session.flowStage === 'WAIT_STUDENT_ACTION'"
                    data-testid="start-voice"
                    :disabled="voiceRecording"
                    :loading="submitting"
                    @click="startVoiceRecording"
                  >开始录音</el-button>
                  <el-button data-testid="request-support" :loading="submitting" @click="requestGuidedSupport">我不会，给我一点提示</el-button>
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
                      :rows="2"
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
                      >
                        提交回答
                      </el-button>
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
                  >我有疑问</el-button>
                  <el-button
                    v-if="session.flowStage === 'WAIT_INITIAL_CHOICE'"
                    data-testid="start-voice-doubt"
                    :disabled="voiceRecording"
                    :loading="submitting"
                    @click="startDoubtVoiceRecording"
                  >开始录音</el-button>
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
          <section v-else-if="session.flowStage === 'SHOWING_FULL_SOLUTION'" class="session-section"><h2>完整解析</h2><p v-if="question">{{ question.fullSolution }}</p><p>请确认你是否已经理解解析；确认后需要从头完成第二轮自讲。</p><div class="actions"><el-button data-testid="understood-solution" type="primary" :loading="submitting" @click="respondToSolution(true)">我会了，开始第二轮自讲</el-button><el-button :loading="submitting" @click="respondToSolution(false)">仍然不会</el-button></div></section>
        </template>
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
.question-content { padding: var(--space-6) 0; border-top: 1px solid var(--color-border); border-bottom: 1px solid var(--color-border); }
.question-content p { max-width: var(--reading-width); margin: var(--space-3) 0 0; color: var(--color-text-primary); font-size: var(--font-size-lg); font-weight: 600; line-height: 1.75; overflow-wrap: anywhere; }
.session-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: var(--space-6); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.summary-item { display: flex; min-width: 0; flex-direction: column; padding: var(--space-4); gap: var(--space-1); }
.summary-item + .summary-item { border-left: 1px solid var(--color-border); }
.summary-item span { color: var(--color-text-muted); font-size: var(--font-size-sm); }
.summary-item strong { font-size: var(--font-size-lg); }
.status-item { align-items: flex-start; }
.session-section { margin-top: var(--space-8); padding-top: var(--space-6); border-top: 1px solid var(--color-border); }
.session-section p { color: var(--color-text-secondary); }
.section-description, .section-heading p, .evaluation-section > div > p { margin: var(--space-1) 0 0; color: var(--color-text-muted); font-size: var(--font-size-sm); }
.evaluation-section { display: grid; grid-template-columns: minmax(220px, 1fr) minmax(300px, 1fr); align-items: center; gap: var(--space-6); }
.evaluation-results { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
.evaluation-result { padding: var(--space-4); border-radius: var(--radius-md); background: var(--color-surface-muted); }
.evaluation-result span { display: block; color: var(--color-text-muted); font-size: var(--font-size-sm); }
.evaluation-result strong { display: block; margin-top: var(--space-1); font-size: var(--font-size-lg); }
.evaluation-result.is-positive { color: var(--color-success-700); background: var(--color-success-100); }
.evaluation-result.is-negative { color: var(--color-error-700); background: var(--color-error-100); }
.evaluation-result.is-attention { color: var(--color-action-700); background: var(--color-action-100); }
.dialog-segmented { width: 100%; margin-top: var(--space-4); overflow-x: auto; }
.dialog-panel {
  margin-top: var(--space-4);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}
.dialog-pane { min-height: 190px; }
.guided-question + .guided-question { margin-top: var(--space-4); }
.guided-question p { margin: 0 0 var(--space-2); color: var(--color-text-primary); font-weight: 600; }
.guided-question .voice-recorder { margin-top: 0; }
.conversation-scroll {
  height: 420px;
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
  justify-content: space-between;
  gap: var(--space-3);
  color: var(--color-text-muted);
  font-size: 12px;
}
.conversation-meta span { color: var(--color-text-primary); font-weight: 700; }
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
  .session-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-item:nth-child(3) { border-top: 1px solid var(--color-border); border-left: 0; }
  .summary-item:nth-child(4) { border-top: 1px solid var(--color-border); }
  .evaluation-section { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .session-page { padding: var(--space-6) var(--space-4) var(--space-8); }
  .page-header { align-items: flex-start; flex-direction: column; }
  .page-header a, .page-header .el-button { width: 100%; }
  .dialog-panel { padding: var(--space-3); }
  .dialog-segmented :deep(.el-segmented__group) { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); width: 100%; }
  .dialog-segmented :deep(.el-segmented__item) { min-width: 0; padding: var(--space-2); white-space: normal; }
  .actions .el-button { flex: 1 1 100%; }
  .conversation-scroll { height: 480px; }
  .conversation-list { padding: var(--space-3); }
  .conversation-message { max-width: 94%; }
  .conversation-meta { flex-direction: column; gap: 0; }
}
@media (max-width: 560px) {
  .dialog-segmented :deep(.el-segmented__item) { padding: 6px 3px; }
  .dialog-segmented :deep(.el-segmented__item-label) { font-size: 12px; }
  .error-state { align-items: stretch; flex-direction: column; }
}
</style>
