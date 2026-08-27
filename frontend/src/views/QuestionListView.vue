<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRouter } from "vue-router"

import {
  archiveQuestion,
  fetchQuestionFilterOptions,
  fetchQuestions,
  restoreQuestion,
} from "../api/questions"
import { createSession } from "../api/sessions"
import { authUser } from "../stores/auth"
import type { QuestionFilterOptions, QuestionListItem } from "../types/question"
import { sanitizeQuestionHtml } from "../utils/questionHtml"

const router = useRouter()
const questions = ref<QuestionListItem[]>([])
const loading = ref(true)
const errorMessage = ref("")
const showArchived = ref(false)
const actingQuestionId = ref<number>()
const filterOptions = ref<QuestionFilterOptions>({ gradePeriods: [], subjects: [] })
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const gradePeriod = ref<number>()
const subject = ref("")
const keyword = ref("")

function evaluationModeLabel(question: QuestionListItem): string {
  return {
    FULL_RUBRIC: "完整评分",
    BASIC: "基础评价",
    AI_GENERAL: "通用评价",
  }[question.evaluationMode]
}

function evaluationModeTagType(question: QuestionListItem): "success" | "warning" | "info" {
  if (question.evaluationMode === "FULL_RUBRIC") return "success"
  if (question.evaluationMode === "BASIC") return "warning"
  return "info"
}

async function loadQuestions() {
  loading.value = true
  errorMessage.value = ""
  try {
    const result = await fetchQuestions({
      page: page.value,
      pageSize: pageSize.value,
      includeArchived: authUser.value?.role === "TEACHER" && showArchived.value,
      gradePeriod: gradePeriod.value,
      subject: subject.value || undefined,
      keyword: keyword.value || undefined,
    })
    questions.value = result.items
    total.value = result.pagination.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function loadFilterOptions() {
  try {
    filterOptions.value = await fetchQuestionFilterOptions(
      authUser.value?.role === "TEACHER" && showArchived.value,
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  }
}

async function resetAndLoadQuestions() {
  page.value = 1
  await loadQuestions()
}

async function changeArchiveScope() {
  page.value = 1
  await Promise.all([loadFilterOptions(), loadQuestions()])
}

async function startSelfExplanation(question: QuestionListItem, restart = false) {
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

async function changeArchiveState(question: QuestionListItem) {
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

onMounted(async () => {
  await Promise.all([loadFilterOptions(), loadQuestions()])
})
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

    <div class="list-toolbar">
      <div class="list-filters">
        <el-select v-model="gradePeriod" clearable placeholder="全部学段" @change="resetAndLoadQuestions">
          <el-option v-for="item in filterOptions.gradePeriods" :key="item" :label="`学段 ${item}`" :value="item" />
        </el-select>
        <el-select v-model="subject" clearable placeholder="全部学科" @change="resetAndLoadQuestions">
          <el-option v-for="item in filterOptions.subjects" :key="item" :label="item" :value="item" />
        </el-select>
        <el-input v-model="keyword" clearable placeholder="检索题干" @keyup.enter="resetAndLoadQuestions" />
        <el-button @click="resetAndLoadQuestions">搜索</el-button>
      </div>
      <el-switch
        v-if="authUser?.role === 'TEACHER'"
        v-model="showArchived"
        active-text="显示已归档"
        @change="changeArchiveScope"
      />
    </div>

    <el-skeleton v-if="loading" :rows="5" animated />
    <el-empty
      v-else-if="questions.length === 0"
      :description="authUser?.role === 'TEACHER' ? '暂未录入题目' : '暂无可自讲题目'"
    />
    <el-table v-else :data="questions" class="question-table" table-layout="fixed">
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column label="题目内容" min-width="360" class-name="question-content-cell">
        <template #default="scope">
          <div class="question-rich-text" v-html="sanitizeQuestionHtml(scope.row.questionContent)" />
        </template>
      </el-table-column>
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
        <template #default="scope">{{ scope.row.rubricPointCount }}</template>
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
        <div class="question-rich-text" v-html="sanitizeQuestionHtml(question.questionContent)" />
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
    <el-pagination
      v-if="!loading && total > 0"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      class="question-pagination"
      background
      layout="total, sizes, prev, pager, next"
      :page-sizes="[20, 50, 100]"
      :total="total"
      @current-change="loadQuestions"
      @size-change="resetAndLoadQuestions"
    />
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
.list-toolbar { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-3) 0; border-bottom: 1px solid var(--color-border); }
.list-filters { display: flex; flex: 1; gap: var(--space-3); }
.question-pagination { justify-content: flex-end; margin-top: var(--space-6); }
.question-table { border-top: 1px solid var(--color-border); }
.question-table :deep(.question-content-cell .cell) { overflow: hidden; display: -webkit-box; white-space: normal; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
.question-rich-text :deep(p) { margin: 0; }
.question-rich-text :deep(img) { display: block; max-width: 100%; height: auto; }

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
  .list-toolbar, .list-filters { align-items: stretch; flex-direction: column; }
  .question-table { display: none; }
  .question-list-mobile { display: grid; gap: var(--space-4); margin-top: var(--space-4); }
  .question-item { padding: var(--space-4) 0 var(--space-6); border-bottom: 1px solid var(--color-border); }
  .question-item-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
  .question-tags { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--space-2); }
  .question-id { color: var(--color-text-muted); font-size: var(--font-size-sm); font-weight: 600; }
  .question-item .question-rich-text { margin: var(--space-3) 0 var(--space-4); overflow-wrap: anywhere; }
  .row-actions { flex-wrap: wrap; }
}
</style>
