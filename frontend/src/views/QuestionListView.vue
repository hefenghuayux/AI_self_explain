<script setup lang="ts">
import { onMounted, ref } from "vue"

import { fetchQuestions } from "../api/questions"
import type { Question } from "../types/question"

const questions = ref<Question[]>([])
const loading = ref(true)
const errorMessage = ref("")
const showArchived = ref(false)

async function loadQuestions() {
  loading.value = true
  errorMessage.value = ""
  try {
    questions.value = await fetchQuestions(showArchived.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

onMounted(loadQuestions)
</script>

<template>
  <main class="question-page">
    <el-card shadow="never">
      <template #header>
        <div class="page-header">
          <div>
            <p class="eyebrow">QUESTION MANAGEMENT</p>
            <h1>题目管理</h1>
          </div>
          <RouterLink to="/questions/new">
            <el-button type="primary">录入题目</el-button>
          </RouterLink>
        </div>
      </template>

      <el-alert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        :closable="false"
        show-icon
      />
      <template v-else>
        <el-switch
          v-model="showArchived"
          class="archive-switch"
          active-text="显示已归档"
          @change="loadQuestions"
        />
        <el-skeleton v-if="loading" :rows="5" animated />
        <el-empty v-else-if="questions.length === 0" description="暂未录入题目" />
        <el-table v-else :data="questions">
          <el-table-column prop="id" label="ID" width="90" />
          <el-table-column prop="questionContent" label="题目内容" min-width="360" />
          <el-table-column label="评分点数" width="110">
            <template #default="scope">{{ scope.row.rubricPoints.length }}</template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="scope">
              <el-tag v-if="scope.row.archivedAt" type="warning">已归档</el-tag>
              <el-tag v-else type="success">可用</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="scope">
              <RouterLink :to="`/questions/${scope.row.id}`">查看</RouterLink>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-card>
  </main>
</template>

<style scoped>
.question-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 24px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

h1 {
  margin: 0;
}

.archive-switch {
  margin-bottom: 16px;
}
</style>
