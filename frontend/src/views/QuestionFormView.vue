<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"

import { createQuestion, fetchQuestion, updateQuestion } from "../api/questions"
import QuestionForm from "../components/QuestionForm.vue"
import { toQuestionInput, type QuestionInput } from "../types/question"

const route = useRoute()
const router = useRouter()
const questionId = route.params.questionId ? String(route.params.questionId) : undefined
const initialQuestion = ref<QuestionInput>()
const loading = ref(Boolean(questionId))
const submitting = ref(false)
const errorMessage = ref("")

onMounted(async () => {
  if (!questionId) {
    return
  }
  try {
    initialQuestion.value = toQuestionInput(await fetchQuestion(questionId))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
})

async function submitQuestion(question: QuestionInput) {
  submitting.value = true
  errorMessage.value = ""
  try {
    const savedQuestion = questionId
      ? await updateQuestion(questionId, question)
      : await createQuestion(question)
    await router.push(`/questions/${savedQuestion.id}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="question-page">
    <el-card shadow="never">
      <template #header>
        <div class="page-header">
          <div>
            <p class="eyebrow">QUESTION ENTRY</p>
            <h1>{{ questionId ? "编辑题目" : "录入题目" }}</h1>
          </div>
          <RouterLink to="/questions"><el-button>取消</el-button></RouterLink>
        </div>
      </template>

      <el-alert
        v-if="errorMessage && !loading"
        :title="errorMessage"
        type="error"
        :closable="false"
        show-icon
      />
      <el-skeleton v-if="loading" :rows="8" animated />
      <QuestionForm
        v-else
        :initial-question="initialQuestion"
        :submitting="submitting"
        :server-error="errorMessage"
        @submit="submitQuestion"
      />
    </el-card>
  </main>
</template>

<style scoped>
.question-page {
  max-width: 960px;
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
</style>
