<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRoute } from "vue-router"

import {
  fetchSession,
  retryEvaluation,
  submitInitialChoice,
  submitTextAttempt,
} from "../api/sessions"
import { fetchQuestion } from "../api/questions"
import type { InitialChoice, Session } from "../types/session"
import type { Question } from "../types/question"

const route = useRoute()
const session = ref<Session>()
const question = ref<Question>()
const confirmedText = ref("")
const loading = ref(true)
const submitting = ref(false)
const errorMessage = ref("")

const sessionId = String(route.params.sessionId)

onMounted(async () => {
  try {
    session.value = await fetchSession(sessionId)
    question.value = await fetchQuestion(String(session.value.questionId))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
})

async function chooseInitialChoice(choice: InitialChoice) {
  if (!session.value) {
    return
  }
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

async function submitText() {
  if (!session.value) {
    return
  }
  if (!confirmedText.value.trim()) {
    errorMessage.value = "请输入自讲内容后再确认提交"
    return
  }
  submitting.value = true
  errorMessage.value = ""
  try {
    session.value = await submitTextAttempt(sessionId, confirmedText.value, session.value.version)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function retryAiEvaluation() {
  if (!session.value) {
    return
  }
  submitting.value = true
  errorMessage.value = ""
  try {
    session.value = await retryEvaluation(sessionId, session.value.version)
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
          <div>
            <p class="eyebrow">SELF EXPLANATION</p>
            <h1>开始自讲</h1>
          </div>
          <RouterLink v-if="session" :to="`/questions/${session.questionId}`"><el-button>返回题目</el-button></RouterLink>
        </div>
      </template>

      <el-alert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        :closable="false"
        show-icon
      />
      <el-skeleton v-else-if="loading" :rows="5" animated />
      <template v-else-if="session">
        <section v-if="question" class="question-content">
          <h2>题目</h2>
          <p data-testid="question-content">{{ question.questionContent }}</p>
        </section>
        <el-descriptions :column="2" border class="session-summary">
          <el-descriptions-item label="会话状态">{{ session.status }}</el-descriptions-item>
          <el-descriptions-item label="当前轮次">第 {{ session.round }} 轮</el-descriptions-item>
        </el-descriptions>

        <section v-if="session.status === 'NEED_HUMAN'" class="session-section">
          <h2>需要人工处理</h2>
          <el-alert
            :title="session.needHumanReason ?? 'AI 评价无法可靠完成，请等待人工处理。'"
            type="warning"
            :closable="false"
            show-icon
          />
        </section>

        <section v-else-if="session.status === 'COMPLETED'" class="session-section">
          <h2>本轮自讲已完成</h2>
          <p v-if="session.latestEvaluation">{{ session.latestEvaluation.feedback }}</p>
        </section>

        <section v-else-if="session.flowStage === 'WAIT_INITIAL_CHOICE'" class="session-section">
          <h2>你现在会讲这道题吗？</h2>
          <p>请选择当前情况，系统会据此继续会话。</p>
          <div class="actions">
            <el-button
              data-testid="initial-choice-know"
              type="primary"
              :loading="submitting"
              @click="chooseInitialChoice('KNOW')"
            >会</el-button>
            <el-button :loading="submitting" @click="chooseInitialChoice('NOT_KNOW')">不会</el-button>
          </div>
        </section>

        <section v-else-if="session.flowStage === 'CAPTURING_INPUT'" class="session-section">
          <h2>请用自己的话讲解</h2>
          <p>人工输入的内容将直接作为本次确认文本保存。</p>
          <el-input
            v-model="confirmedText"
            type="textarea"
            :rows="8"
            placeholder="请输入你的自讲内容"
            :disabled="submitting"
          />
          <div class="actions">
            <el-button data-testid="submit-text" type="primary" :loading="submitting" @click="submitText">
              确认提交
            </el-button>
          </div>
        </section>

        <section v-else-if="session.flowStage === 'CONFIRMING_TEXT'" class="session-section">
          <h2>AI 服务暂时不可用</h2>
          <p>确认文本已保留。你可以重新发起评价，不需要重新输入。</p>
          <div class="actions">
            <el-button
              data-testid="retry-evaluation"
              type="primary"
              :loading="submitting"
              @click="retryAiEvaluation"
            >重新评价</el-button>
          </div>
        </section>

        <section v-else-if="session.flowStage === 'AI_EVALUATING'" class="session-section">
          <h2>AI 正在评价</h2>
          <p>请等待评价结果返回。</p>
        </section>

        <section
          v-else-if="session.flowStage === 'WAIT_STUDENT_ACTION' && session.latestEvaluation"
          class="session-section"
        >
          <h2>AI 结构化评价</h2>
          <p data-testid="ai-feedback">{{ session.latestEvaluation.feedback }}</p>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="正确性">{{ session.latestEvaluation.correctness }}</el-descriptions-item>
            <el-descriptions-item label="完整性">{{ session.latestEvaluation.completeness }}</el-descriptions-item>
            <el-descriptions-item label="已覆盖评分点">
              {{ session.latestEvaluation.coveredPoints.join("；") }}
            </el-descriptions-item>
            <el-descriptions-item label="缺失评分点">
              {{ session.latestEvaluation.missingPoints.join("；") }}
            </el-descriptions-item>
          </el-descriptions>
          <ul v-if="session.latestEvaluation.errorEvidence.length" class="evidence-list">
            <li v-for="evidence in session.latestEvaluation.errorEvidence" :key="evidence.quote">
              “{{ evidence.quote }}”：{{ evidence.reason }}。{{ evidence.thinkingDirection }}
            </li>
          </ul>
          <p>后续教学操作将在阶段 05 接入。</p>
        </section>

        <section v-else class="session-section">
          <h2>当前选择已保存</h2>
          <p>本阶段仅建立会话状态骨架，后续阶段将继续处理该流程。</p>
        </section>
      </template>
    </el-card>
  </main>
</template>

<style scoped>
.session-page {
  max-width: 800px;
  margin: 0 auto;
  padding: 24px;
}

.page-header,
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-header {
  justify-content: space-between;
}

.eyebrow {
  margin: 0 0 8px;
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

h1,
h2 {
  margin: 0;
}

.session-summary,
.question-content,
.session-section {
  margin-top: 20px;
}

.question-content p,
.session-section p {
  color: #606266;
}

.actions {
  margin-top: 16px;
}

.evidence-list {
  margin: 16px 0 0;
  padding-left: 20px;
  color: #606266;
}
</style>
