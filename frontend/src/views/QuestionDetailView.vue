<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"

import { archiveQuestion, fetchQuestion, restoreQuestion } from "../api/questions"
import { createSession } from "../api/sessions"
import type { Question } from "../types/question"

const route = useRoute()
const router = useRouter()
const question = ref<Question>()
const loading = ref(true)
const errorMessage = ref("")
const changingArchiveState = ref(false)
const creatingSession = ref(false)

onMounted(async () => {
  try {
    question.value = await fetchQuestion(String(route.params.questionId))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
})

async function changeArchiveState() {
  if (!question.value) {
    return
  }
  changingArchiveState.value = true
  errorMessage.value = ""
  try {
    question.value = question.value.archivedAt
      ? await restoreQuestion(String(question.value.id))
      : await archiveQuestion(String(question.value.id))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    changingArchiveState.value = false
  }
}

async function startSession() {
  if (!question.value) {
    return
  }
  creatingSession.value = true
  errorMessage.value = ""
  try {
    const session = await createSession(String(question.value.id))
    await router.push(`/sessions/${session.id}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    creatingSession.value = false
  }
}
</script>

<template>
  <main class="question-page">
    <div class="page-header">
      <div>
        <h1>题目详情</h1>
        <p>查看题目与 AI 评价所需的完整材料。</p>
      </div>
          <div class="actions">
            <RouterLink to="/questions"><el-button>返回列表</el-button></RouterLink>
            <RouterLink v-if="question && !question.archivedAt" :to="`/questions/${question.id}/edit`">
              <el-button type="primary">编辑题目</el-button>
            </RouterLink>
            <el-button
              v-if="question && !question.archivedAt"
              type="success"
              :loading="creatingSession"
              @click="startSession"
            >
              开始自讲
            </el-button>
            <el-button
              v-if="question"
              :type="question.archivedAt ? 'success' : 'warning'"
              :loading="changingArchiveState"
              @click="changeArchiveState"
            >
              {{ question.archivedAt ? "恢复题目" : "归档题目" }}
            </el-button>
          </div>
    </div>
    <section class="detail-surface">

      <el-alert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        :closable="false"
        show-icon
      />
      <el-skeleton v-else-if="loading" :rows="8" animated />
      <el-descriptions v-else-if="question" :column="1" border>
        <el-descriptions-item label="状态">
          <el-tag :type="question.archivedAt ? 'warning' : 'success'">
            {{ question.archivedAt ? "已归档" : "可用" }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="题目内容">{{ question.questionContent }}</el-descriptions-item>
        <el-descriptions-item label="标准答案">{{ question.standardAnswer }}</el-descriptions-item>
        <el-descriptions-item label="关键评分点">
          <ul><li v-for="item in question.rubricPoints" :key="item">{{ item }}</li></ul>
        </el-descriptions-item>
        <el-descriptions-item label="常见错误">
          <ul><li v-for="item in question.commonErrors" :key="item">{{ item }}</li></ul>
        </el-descriptions-item>
        <el-descriptions-item label="可接受的其他解法">
          <ul><li v-for="item in question.alternativeSolutions" :key="item">{{ item }}</li></ul>
        </el-descriptions-item>
        <el-descriptions-item label="分层提示">
          <ul><li v-for="item in question.layeredHints" :key="item">{{ item }}</li></ul>
        </el-descriptions-item>
        <el-descriptions-item label="提示子问题">
          <ul v-if="question.guidedQuestions.length">
            <li v-for="item in question.guidedQuestions" :key="item">{{ item }}</li>
          </ul>
          <span v-else class="empty-value">未配置</span>
        </el-descriptions-item>
        <el-descriptions-item label="完整解析">{{ question.fullSolution }}</el-descriptions-item>
      </el-descriptions>
    </section>
  </main>
</template>

<style scoped>
.question-page {
  max-width: 960px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-6) var(--space-12);
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

h1 {
  margin: 0;
  font-size: var(--font-size-2xl);
  line-height: 1.35;
}
.page-header > div:first-child > p { margin: var(--space-2) 0 0; color: var(--color-text-secondary); }
.detail-surface { margin-top: var(--space-8); padding-top: var(--space-6); border-top: 1px solid var(--color-border); }
.detail-surface :deep(.el-descriptions__content) { line-height: 1.75; white-space: pre-wrap; overflow-wrap: anywhere; }
.detail-surface :deep(.el-descriptions__label) { width: 160px; color: var(--color-text-primary); font-weight: 600; }

ul {
  margin: 0;
  padding-left: 20px;
}

.empty-value {
  color: var(--color-text-muted);
}
@media (max-width: 640px) { .question-page { padding: var(--space-6) var(--space-4) var(--space-8); } .page-header { align-items: flex-start; flex-direction: column; } .actions { width: 100%; flex-wrap: wrap; } .actions a, .actions .el-button { flex: 1 1 auto; } .detail-surface :deep(.el-descriptions__label) { width: 112px; } }
</style>
