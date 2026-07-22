<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRoute } from "vue-router"

import {
  askDoubt,
  confirmVoiceAttempt,
  continueExplaining,
  fetchLearningTimeline,
  fetchSession,
  requestSupport,
  retryEvaluation,
  submitAppeal,
  submitGuidedAnswers,
  submitInitialChoice,
  submitSolutionUnderstanding,
  submitTextAttempt,
} from "../api/sessions"
import VoiceRecorder from "../components/VoiceRecorder.vue"
import { fetchQuestion } from "../api/questions"
import type { AIEvaluation, GuidedAnswer, InitialChoice, LearningTimelineItem, Session, SessionStatus } from "../types/session"
import type { Question } from "../types/question"

const route = useRoute()
const session = ref<Session>()
const question = ref<Question>()
const timeline = ref<LearningTimelineItem[]>([])
const draftText = ref("")
const doubtText = ref("")
const guidedAnswerText = ref<Record<string, string>>({})
const appealReason = ref("")
const emptyDraftReminderShown = ref(false)
const unchangedDraftReminderShown = ref(false)
const loading = ref(true)
const submitting = ref(false)
const errorMessage = ref("")
const voiceRecording = ref(false)

const sessionId = String(route.params.sessionId)

const sessionStatusLabels: Record<SessionStatus, string> = {
  IN_PROGRESS: "进行中",
  COMPLETED: "已完成",
  STOPPED_LIMIT: "已达到支持上限",
  NEED_HUMAN: "需要人工帮助",
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
  NEED_HUMAN: "转人工帮助",
}

const timelineEventLabels: Record<LearningTimelineItem["eventType"], string> = {
  EVALUATION: "学习反馈",
  SUPPORT: "学习支持",
  FULL_SOLUTION: "完整解析",
  NEED_HUMAN: "已转人工帮助",
}

onMounted(async () => {
  try {
    session.value = await fetchSession(sessionId)
    draftText.value = session.value.currentDraft
    question.value = await fetchQuestion(String(session.value.questionId))
    timeline.value = await fetchLearningTimeline(sessionId)
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
  return item.action ? actionLabels[item.action] : timelineEventLabels[item.eventType]
}

function resetDraftReminderIfChanged() {
  if (session.value && draftText.value !== session.value.currentDraft) {
    unchangedDraftReminderShown.value = false
  }
}

function canRequestSupport() {
  resetDraftReminderIfChanged()
  if (!draftText.value.trim() && !emptyDraftReminderShown.value) {
    emptyDraftReminderShown.value = true
    errorMessage.value = "请先输入当前的题干理解或者解题、分析过程；再次点击可继续。"
    return false
  }
  if (
    session.value?.flowStage === "WAIT_STUDENT_ACTION"
    && draftText.value === session.value.currentDraft
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
    errorMessage.value = "请先停止录音，确认转写后再提交自讲"
    return
  }
  if (!draftText.value.trim()) {
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
    session.value = await submitTextAttempt(sessionId, draftText.value, session.value.version)
    draftText.value = session.value.currentDraft
    await refreshTimeline()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function prepareVoiceInput() {
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

function appendFinalTranscript(text: string) {
  draftText.value = draftText.value.trimEnd()
  draftText.value = draftText.value ? `${draftText.value}\n${text}` : text
}

async function handleVoiceCompleted() {
  try {
    session.value = await fetchSession(sessionId)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  }
}

async function confirmVoiceTranscript() {
  if (!session.value?.pendingVoiceAttempt || !draftText.value.trim()) {
    errorMessage.value = "请确认或修改转写文本后再提交"
    return
  }
  submitting.value = true
  errorMessage.value = ""
  try {
    session.value = await confirmVoiceAttempt(
      sessionId,
      session.value.pendingVoiceAttempt.id,
      draftText.value,
      session.value.version,
    )
    draftText.value = session.value.currentDraft
    await refreshTimeline()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
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
    session.value = await requestSupport(sessionId, draftText.value, session.value.version)
    draftText.value = session.value.currentDraft
    await refreshTimeline()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function submitDoubt() {
  if (!session.value) return
  if (!doubtText.value.trim()) {
    errorMessage.value = "请先输入你的疑问"
    return
  }
  submitting.value = true
  errorMessage.value = ""
  try {
    if (session.value.flowStage === "WAIT_INITIAL_CHOICE") {
      session.value = await submitInitialChoice(sessionId, "HAS_QUESTION", session.value.version)
    }
    session.value = await askDoubt(sessionId, draftText.value, doubtText.value, session.value.version)
    draftText.value = session.value.currentDraft
    doubtText.value = ""
    await refreshTimeline()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function submitGuidedQuestionAnswers() {
  if (!session.value || !session.value.latestSupport?.guidedQuestions) return
  const answers: GuidedAnswer[] = session.value.latestSupport.guidedQuestions.map((item) => ({
    questionId: item.id,
    answer: guidedAnswerText.value[item.id]?.trim() ?? "",
  }))
  if (answers.some((item) => !item.answer)) {
    errorMessage.value = "请回答全部子问题后再提交"
    return
  }
  submitting.value = true
  errorMessage.value = ""
  try {
    session.value = await submitGuidedAnswers(sessionId, answers, session.value.version)
    guidedAnswerText.value = {}
    await refreshTimeline()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function retryAiEvaluation() {
  if (!session.value) return
  submitting.value = true
  errorMessage.value = ""
  try {
    session.value = await retryEvaluation(sessionId, session.value.version)
    await refreshTimeline()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function appealEvaluation() {
  if (!session.value || !appealReason.value.trim()) {
    errorMessage.value = "请填写不同意 AI 判断的理由"
    return
  }
  submitting.value = true
  errorMessage.value = ""
  try {
    session.value = await submitAppeal(sessionId, appealReason.value, session.value.version)
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
    draftText.value = session.value.currentDraft
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
    <el-card shadow="never">
      <template #header>
        <div class="page-header">
          <div><p class="eyebrow">SELF EXPLANATION</p><h1>开始自讲</h1></div>
          <RouterLink v-if="session" to="/"><el-button>返回题目列表</el-button></RouterLink>
        </div>
      </template>
      <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />
      <el-skeleton v-else-if="loading" :rows="5" animated />
      <template v-else-if="session">
        <section v-if="question" class="question-content"><h2>题目</h2><p data-testid="question-content">{{ question.questionContent }}</p></section>
        <el-descriptions :column="2" border class="session-summary">
          <el-descriptions-item label="会话状态">{{ sessionStatusLabels[session.status] }}</el-descriptions-item>
          <el-descriptions-item label="当前轮次">第 {{ session.round }} 轮</el-descriptions-item>
          <el-descriptions-item label="本轮有效支持">{{ session.supportCountRound }}</el-descriptions-item>
          <el-descriptions-item label="累计有效支持">{{ session.supportCountTotal }}</el-descriptions-item>
        </el-descriptions>
        <section v-if="session.latestEvaluation" class="session-section"><h2>本次自讲评价</h2><el-descriptions :column="2" border><el-descriptions-item label="正确性">{{ correctnessLabels[session.latestEvaluation.correctness] }}</el-descriptions-item><el-descriptions-item label="完整性">{{ completenessLabels[session.latestEvaluation.completeness] }}</el-descriptions-item></el-descriptions></section>
        <section v-if="timeline.length" class="session-section"><h2>学习反馈记录</h2><el-timeline><el-timeline-item v-for="item in timeline" :key="item.id" :timestamp="new Date(item.createdAt).toLocaleString('zh-CN', { hour12: false })"><div class="timeline-title">{{ timelineTitle(item) }}</div><p v-if="item.correctness && item.completeness" class="timeline-evaluation">正确性：{{ correctnessLabels[item.correctness] }}；完整性：{{ completenessLabels[item.completeness] }}</p><p data-testid="timeline-content">{{ item.content }}</p></el-timeline-item></el-timeline></section>
        <section v-if="session.status === 'NEED_HUMAN'" class="session-section"><h2>需要人工处理</h2><el-alert title="暂无法可靠判断，已转人工帮助。" type="warning" :closable="false" show-icon /></section>
        <section v-else-if="session.status === 'COMPLETED'" class="session-section"><h2>本轮自讲已完成</h2></section>
        <section v-else-if="session.status === 'STOPPED_LIMIT'" class="session-section"><h2>已达到本轮支持上限</h2><p v-if="question">{{ question.fullSolution }}</p></section>
        <template v-else>
          <section class="session-section"><h2>当前解题过程</h2><p>这里会保留你的内容；每次提交都会保存独立的自讲快照。</p><el-input v-model="draftText" data-testid="main-draft" type="textarea" :rows="8" placeholder="输入题干理解、分析过程或完整自讲" :disabled="submitting || session.flowStage === 'AI_EVALUATING'" /><VoiceRecorder v-if="session.flowStage === 'CAPTURING_INPUT'" :session-id="sessionId" :version="session.version" :disabled="submitting" @final-transcript="appendFinalTranscript" @completed="handleVoiceCompleted" @recording-change="voiceRecording = $event" @error="errorMessage = $event" /></section>
          <section v-if="session.flowStage === 'WAIT_GUIDED_ANSWERS'" class="session-section"><h2>请回答这些问题</h2><template v-for="item in session.latestSupport?.guidedQuestions" :key="item.id"><p>{{ item.question }}</p><el-input v-model="guidedAnswerText[item.id]" type="textarea" :rows="2" :disabled="submitting" /></template><div class="actions"><el-button data-testid="submit-guided-answers" type="primary" :loading="submitting" @click="submitGuidedQuestionAnswers">提交子问题答案</el-button></div></section>
          <section v-else-if="session.flowStage === 'CONFIRMING_TEXT' && session.pendingVoiceAttempt" class="session-section"><h2>确认语音转写</h2><p>原始转写：{{ session.pendingVoiceAttempt.asrTranscript }}</p><p>你可以继续修改上方“当前解题过程”中的文本，确认后才会进入 AI 评价。</p><div class="actions"><el-button data-testid="confirm-voice-transcript" type="primary" :loading="submitting" @click="confirmVoiceTranscript">确认并提交自讲</el-button></div></section>
          <section v-else-if="session.flowStage === 'CONFIRMING_TEXT'" class="session-section"><h2>AI 服务暂时不可用</h2><p>确认文本已保留。你可以重新发起评价。</p><div class="actions"><el-button data-testid="retry-evaluation" type="primary" :loading="submitting" @click="retryAiEvaluation">重新评价</el-button></div></section>
          <section v-else-if="session.flowStage === 'AI_EVALUATING'" class="session-section"><h2>AI 正在评价</h2><p>请等待评价结果返回。</p></section>
          <section v-else-if="session.flowStage === 'SHOWING_FULL_SOLUTION'" class="session-section"><h2>完整解析</h2><p v-if="question">{{ question.fullSolution }}</p><p>请确认你是否已经理解解析；确认后需要从头完成第二轮自讲。</p><div class="actions"><el-button data-testid="understood-solution" type="primary" :loading="submitting" @click="respondToSolution(true)">我会了，开始第二轮自讲</el-button><el-button :loading="submitting" @click="respondToSolution(false)">仍然不会</el-button></div></section>
          <section v-else class="session-section"><h2 v-if="session.flowStage === 'WAIT_INITIAL_CHOICE'">请开始你的解题过程</h2><div class="actions"><el-button data-testid="submit-explanation" type="primary" :loading="submitting" @click="submitExplanation">提交自讲</el-button><el-button data-testid="prepare-voice" :loading="submitting" @click="prepareVoiceInput">使用语音自讲</el-button><el-button data-testid="request-support" :loading="submitting" @click="requestGuidedSupport">我不会，给我一点提示</el-button></div><el-input v-model="doubtText" class="doubt-input" placeholder="我有疑问：请输入疑问点" :disabled="submitting" /><div class="actions"><el-button data-testid="submit-doubt" :loading="submitting" @click="submitDoubt">我有疑问</el-button></div></section>
          <template v-if="session.latestEvaluation && session.flowStage === 'WAIT_STUDENT_ACTION'"><el-input v-model="appealReason" class="appeal-input" placeholder="如不同意 AI 判断，请填写理由" :disabled="submitting" /><div class="actions"><el-button data-testid="submit-appeal" type="warning" :loading="submitting" @click="appealEvaluation">我不同意 AI 判断</el-button></div></template>
        </template>
      </template>
    </el-card>
  </main>
</template>

<style scoped>
.session-page { max-width: 800px; margin: 0 auto; padding: 24px; }
.page-header, .actions { display: flex; align-items: center; gap: 8px; }
.page-header { justify-content: space-between; }
.eyebrow { margin: 0 0 8px; color: #2563eb; font-size: 12px; font-weight: 700; letter-spacing: 0.14em; }
h1, h2 { margin: 0; }
.session-summary, .question-content, .session-section { margin-top: 20px; }
.question-content p, .session-section p { color: #606266; }
.actions { margin-top: 16px; }
.timeline-title { font-weight: 700; }
.timeline-evaluation { margin: 8px 0; color: #606266; }
.appeal-input, .doubt-input { margin-top: 16px; }
</style>
