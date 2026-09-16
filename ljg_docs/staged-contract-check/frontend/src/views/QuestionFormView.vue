<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"

import { createQuestion, fetchQuestion, updateQuestion } from "../api/questions"
import QuestionForm from "../components/QuestionForm.vue"
import { toQuestionFormInput, type QuestionFormInput, type QuestionInput } from "../types/question"

const route = useRoute()
const router = useRouter()
const questionId = route.params.questionId ? String(route.params.questionId) : undefined
const initialQuestion = ref<QuestionFormInput>()
const loading = ref(Boolean(questionId))
const submitting = ref(false)
const errorMessage = ref("")

onMounted(async () => {
  if (!questionId) {
    return
  }
  try {
    initialQuestion.value = toQuestionFormInput(await fetchQuestion(questionId))
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
    <div class="page-header">
      <div>
        <h1>{{ questionId ? "编辑题目" : "录入题目" }}</h1>
        <p>题目内容必填；评分点等 AI 材料可逐步补录。</p>
      </div>
      <RouterLink to="/questions"><el-button>取消</el-button></RouterLink>
    </div>
    <section class="form-surface">
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
    </section>
  </main>
</template>

<style scoped>
.question-page {
  max-width: 960px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-6) var(--space-12);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

h1 {
  margin: 0;
  font-size: var(--font-size-2xl);
  line-height: 1.35;
}
.page-header p { margin: var(--space-2) 0 0; color: var(--color-text-secondary); }
.form-surface { margin-top: var(--space-8); padding-top: var(--space-6); border-top: 1px solid var(--color-border); }
@media (max-width: 640px) { .question-page { padding: var(--space-6) var(--space-4) var(--space-8); } .page-header { align-items: flex-start; flex-direction: column; } .page-header a, .page-header .el-button { width: 100%; } }
</style>
