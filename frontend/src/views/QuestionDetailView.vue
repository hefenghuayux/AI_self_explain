<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRoute } from "vue-router"

import { fetchQuestion } from "../api/questions"
import type { Question } from "../types/question"

const route = useRoute()
const question = ref<Question>()
const loading = ref(true)
const errorMessage = ref("")

onMounted(async () => {
  try {
    question.value = await fetchQuestion(String(route.params.questionId))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main class="question-page">
    <el-card shadow="never">
      <template #header>
        <div class="page-header">
          <div>
            <p class="eyebrow">QUESTION DETAIL</p>
            <h1>题目详情</h1>
          </div>
          <div class="actions">
            <RouterLink to="/questions"><el-button>返回列表</el-button></RouterLink>
            <RouterLink v-if="question" :to="`/questions/${question.id}/edit`">
              <el-button type="primary">编辑题目</el-button>
            </RouterLink>
          </div>
        </div>
      </template>

      <el-alert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        :closable="false"
        show-icon
      />
      <el-skeleton v-else-if="loading" :rows="8" animated />
      <el-descriptions v-else-if="question" :column="1" border>
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
        <el-descriptions-item label="完整解析">{{ question.fullSolution }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </main>
</template>

<style scoped>
.question-page {
  max-width: 960px;
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

h1 {
  margin: 0;
}

ul {
  margin: 0;
  padding-left: 20px;
}
</style>
