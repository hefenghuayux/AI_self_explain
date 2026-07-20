<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRoute } from "vue-router"

import { fetchSession, submitInitialChoice, submitTextAttempt } from "../api/sessions"
import type { InitialChoice, Session } from "../types/session"

const route = useRoute()
const session = ref<Session>()
const confirmedText = ref("")
const loading = ref(true)
const submitting = ref(false)
const errorMessage = ref("")

const sessionId = String(route.params.sessionId)

onMounted(async () => {
  try {
    session.value = await fetchSession(sessionId)
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
        <el-descriptions :column="2" border class="session-summary">
          <el-descriptions-item label="会话状态">{{ session.status }}</el-descriptions-item>
          <el-descriptions-item label="当前轮次">第 {{ session.round }} 轮</el-descriptions-item>
        </el-descriptions>

        <section v-if="session.flowStage === 'WAIT_INITIAL_CHOICE'" class="session-section">
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

        <section v-else-if="session.flowStage === 'AI_EVALUATING'" class="session-section">
          <h2>自讲内容已保存</h2>
          <p>当前阶段只保存确认文本，AI 评价将在后续阶段接入。</p>
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
.session-section {
  margin-top: 20px;
}

.session-section p {
  color: #606266;
}

.actions {
  margin-top: 16px;
}
</style>
