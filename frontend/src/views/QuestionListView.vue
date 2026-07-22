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

async function startSelfExplanation(question: Question) {
  if (question.archivedAt) return
  actingQuestionId.value = question.id
  errorMessage.value = ""
  try {
    const session = await createSession(String(question.id))
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
        <p class="eyebrow">QUESTIONS</p>
        <h1>题目列表</h1>
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
    <el-table v-else :data="questions" class="question-table">
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="questionContent" label="题目内容" min-width="360" />
      <el-table-column
        v-if="authUser?.role === 'TEACHER'"
        label="评分点数"
        width="110"
      >
        <template #default="scope">{{ scope.row.rubricPoints.length }}</template>
      </el-table-column>
      <el-table-column v-if="authUser?.role === 'TEACHER'" label="状态" width="100">
        <template #default="scope">
          <el-tag v-if="scope.row.archivedAt" type="warning">已归档</el-tag>
          <el-tag v-else type="success">可用</el-tag>
        </template>
      </el-table-column>
      <el-table-column
        label="操作"
        :width="authUser?.role === 'TEACHER' ? 330 : 110"
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
              自讲
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
  </main>
</template>

<style scoped>
.question-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 24px;
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

.eyebrow {
  margin: 0 0 8px;
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
}

h1 {
  margin: 0;
  font-size: 28px;
}

.page-alert,
.list-toolbar,
.question-table {
  margin-top: 20px;
}

.row-actions {
  min-height: 32px;
  flex-wrap: nowrap;
}

@media (max-width: 640px) {
  .question-page {
    padding: 24px 16px;
  }

  .page-header {
    align-items: flex-start;
  }
}
</style>
