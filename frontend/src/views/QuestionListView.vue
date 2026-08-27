<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRouter } from "vue-router"

import { archiveQuestion, fetchQuestions, restoreQuestion } from "../api/questions"
import { createSession } from "../api/sessions"
import { authUser } from "../stores/auth"
import type { Question } from "../types/question"

const router = useRouter()
const questions = ref<Question[]>([])
const loading = ref(true)
const errorMessage = ref("")
const showArchived = ref(false)
const actingQuestionId = ref<number>()

function evaluationModeLabel(question: Question): string {
  return {
    FULL_RUBRIC: "完整评分",
    BASIC: "基础评价",
    AI_GENERAL: "通用评价",
  }[question.evaluationMode]
}

function evaluationModeTagType(question: Question): "success" | "warning" | "info" {
  if (question.evaluationMode === "FULL_RUBRIC") return "success"
  if (question.evaluationMode === "BASIC") return "warning"
  return "info"
}

async function loadQuestions() {
  loading.value = true
  errorMessage.value = ""
  try {
    questions.value = await fetchQuestions(authUser.value?.role === "TEACHER" && showArchived.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function startSelfExplanation(question: Question, restart = false) {
  if (question.archivedAt) return
  actingQuestionId.value = question.id
  errorMessage.value = ""
  try {
    const session = await createSession(String(question.id), restart)
    await router.push(`/sessions/${session.id}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    actingQuestionId.value = undefined
  }
}

async function changeArchiveState(question: Question) {
  actingQuestionId.value = question.id
  errorMessage.value = ""
  try {
    if (question.archivedAt) await restoreQuestion(String(question.id))
    else await archiveQuestion(String(question.id))
    await loadQuestions()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    actingQuestionId.value = undefined
  }
}

onMounted(loadQuestions)
</script>

<template>
  <main class="question-page">
    <div class="page-header">
      <div>
        <h1>题目列表</h1>
        <p>选择一道题目，开始用自己的语言讲清解题过程。</p>
      </div>
      <RouterLink v-if="authUser?.role === 'TEACHER'" to="/questions/new">
        <el-button type="primary">录入题目</el-button>
      </RouterLink>
    </div>

    <el-alert
      v-if="errorMessage"
      class="page-alert"
      :title="errorMessage"
      type="error"
      :closable="false"
      show-icon
    />

    <div v-if="authUser?.role === 'TEACHER'" class="list-toolbar">
      <el-switch
        v-model="showArchived"
        active-text="显示已归档"
        @change="loadQuestions"
      />
    </div>

    <el-skeleton v-if="loading" :rows="5" animated />
    <el-empty
      v-else-if="questions.length === 0"
      :description="authUser?.role === 'TEACHER' ? '暂未录入题目' : '暂无可自讲题目'"
    />
    <el-table v-else :data="questions" class="question-table" table-layout="fixed">
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="questionContent" label="题目内容" min-width="360" class-name="question-content-cell" />
      <el-table-column label="评价方式" width="110">
        <template #default="scope">
          <el-tag :type="evaluationModeTagType(scope.row)">{{ evaluationModeLabel(scope.row) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column
        v-if="authUser?.role === 'TEACHER'"
        label="评分点数"
        width="110"
      >
        <template #default="scope">{{ scope.row.rubricPoints?.length ?? 0 }}</template>
      </el-table-column>
      <el-table-column v-if="authUser?.role === 'TEACHER'" label="状态" width="100">
        <template #default="scope">
          <el-tag v-if="scope.row.archivedAt" type="warning">已归档</el-tag>
          <el-tag v-else type="success">可用</el-tag>
        </template>
      </el-table-column>
      <el-table-column
        label="操作"
        :width="authUser?.role === 'TEACHER' ? 420 : 200"
        fixed="right"
      >
        <template #default="scope">
          <div class="row-actions">
            <el-button
              v-if="!scope.row.archivedAt"
              type="success"
              size="small"
              :loading="actingQuestionId === scope.row.id"
              @click="startSelfExplanation(scope.row)"
            >
              开始自讲
            </el-button>
            <el-button
              v-if="!scope.row.archivedAt"
              size="small"
              :loading="actingQuestionId === scope.row.id"
              @click="startSelfExplanation(scope.row, true)"
            >
              重新自讲
            </el-button>
            <template v-if="authUser?.role === 'TEACHER'">
              <RouterLink :to="`/questions/${scope.row.id}`">
                <el-button size="small">查看</el-button>
              </RouterLink>
              <RouterLink v-if="!scope.row.archivedAt" :to="`/questions/${scope.row.id}/edit`">
                <el-button size="small">编辑</el-button>
              </RouterLink>
              <el-button
                size="small"
                :type="scope.row.archivedAt ? 'success' : 'warning'"
                :loading="actingQuestionId === scope.row.id"
                @click="changeArchiveState(scope.row)"
              >
                {{ scope.row.archivedAt ? "恢复" : "归档" }}
              </el-button>
            </template>
          </div>
        </template>
      </el-table-column>
    </el-table>
    <div v-if="!loading && questions.length" class="question-list-mobile">
      <article v-for="question in questions" :key="question.id" class="question-item">
        <div class="question-item-head">
          <span class="question-id">题目 {{ question.id }}</span>
          <div class="question-tags">
            <el-tag :type="evaluationModeTagType(question)">{{ evaluationModeLabel(question) }}</el-tag>
            <el-tag v-if="authUser?.role === 'TEACHER'" :type="question.archivedAt ? 'warning' : 'success'">
              {{ question.archivedAt ? "已归档" : "可用" }}
            </el-tag>
          </div>
        </div>
        <p>{{ question.questionContent }}</p>
        <div class="row-actions">
          <el-button v-if="!question.archivedAt" type="success" :loading="actingQuestionId === question.id" @click="startSelfExplanation(question)">开始自讲</el-button>
          <el-button v-if="!question.archivedAt" :loading="actingQuestionId === question.id" @click="startSelfExplanation(question, true)">重新自讲</el-button>
          <template v-if="authUser?.role === 'TEACHER'">
            <RouterLink :to="`/questions/${question.id}`"><el-button>查看详情</el-button></RouterLink>
            <RouterLink v-if="!question.archivedAt" :to="`/questions/${question.id}/edit`"><el-button>编辑</el-button></RouterLink>
            <el-button :type="question.archivedAt ? 'success' : 'warning'" :loading="actingQuestionId === question.id" @click="changeArchiveState(question)">{{ question.archivedAt ? "恢复" : "归档" }}</el-button>
          </template>
        </div>
      </article>
    </div>
  </main>
</template>

<style scoped>
.question-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-6) var(--space-12);
}

.page-header,
.row-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-header {
  justify-content: space-between;
  gap: 16px;
}
h1 {
  margin: 0;
  font-size: var(--font-size-2xl);
  line-height: 1.35;
}
.page-header p { margin: var(--space-2) 0 0; color: var(--color-text-secondary); }

.page-alert,
.list-toolbar,
.question-table {
  margin-top: var(--space-6);
}
.list-toolbar { display: flex; justify-content: flex-end; padding: var(--space-3) 0; border-bottom: 1px solid var(--color-border); }
.question-table { border-top: 1px solid var(--color-border); }
.question-table :deep(.question-content-cell .cell) { overflow: hidden; display: -webkit-box; white-space: normal; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }

.row-actions {
  min-height: 32px;
  flex-wrap: nowrap;
}
.question-list-mobile { display: none; }

@media (max-width: 640px) {
  .question-page {
    padding: var(--space-6) var(--space-4) var(--space-8);
  }

  .page-header {
    align-items: flex-start;
    flex-direction: column;
  }
  .page-header a, .page-header .el-button { width: 100%; }
  .question-table { display: none; }
  .question-list-mobile { display: grid; gap: var(--space-4); margin-top: var(--space-4); }
  .question-item { padding: var(--space-4) 0 var(--space-6); border-bottom: 1px solid var(--color-border); }
  .question-item-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
  .question-tags { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--space-2); }
  .question-id { color: var(--color-text-muted); font-size: var(--font-size-sm); font-weight: 600; }
  .question-item p { margin: var(--space-3) 0 var(--space-4); overflow-wrap: anywhere; }
  .row-actions { flex-wrap: wrap; }
}
</style>
