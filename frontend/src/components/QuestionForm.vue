<script setup lang="ts">
import { reactive, ref, watch } from "vue"

import { createQuestionDraft, type QuestionFormInput, type QuestionInput } from "../types/question"

const props = defineProps<{
  initialQuestion?: QuestionFormInput
  submitting: boolean
  serverError: string
}>()

const emit = defineEmits<{
  submit: [question: QuestionInput]
}>()

const form = reactive<QuestionFormInput>(createQuestionDraft())
const validationError = ref("")

watch(
  () => props.initialQuestion,
  (question) => {
    Object.assign(form, question ? cloneQuestion(question) : createQuestionDraft())
    validationError.value = ""
  },
  { immediate: true },
)

function cloneQuestion(question: QuestionFormInput): QuestionFormInput {
  return {
    ...question,
    rubricPoints: [...question.rubricPoints],
    commonErrors: [...question.commonErrors],
    alternativeSolutions: [...question.alternativeSolutions],
    layeredHints: [...question.layeredHints],
    guidedQuestions: [...question.guidedQuestions],
  }
}

function addArrayItem(field: keyof Pick<QuestionFormInput, "rubricPoints" | "commonErrors" | "alternativeSolutions" | "layeredHints" | "guidedQuestions">) {
  form[field].push("")
}

function removeArrayItem(
  field: keyof Pick<QuestionFormInput, "rubricPoints" | "commonErrors" | "alternativeSolutions" | "layeredHints" | "guidedQuestions">,
  index: number,
) {
  form[field].splice(index, 1)
}

function normalizeQuestion(question: QuestionFormInput): QuestionInput {
  return {
    questionContent: question.questionContent.trim(),
    standardAnswer: nullableText(question.standardAnswer),
    rubricPoints: nullableList(question.rubricPoints),
    commonErrors: nullableList(question.commonErrors),
    alternativeSolutions: nullableList(question.alternativeSolutions),
    layeredHints: nullableList(question.layeredHints),
    guidedQuestions: nullableList(question.guidedQuestions),
    fullSolution: nullableText(question.fullSolution),
  }
}

function nullableText(value: string): string | null {
  const normalized = value.trim()
  return normalized || null
}

function nullableList(values: string[]): string[] | null {
  const normalized = values.map((item) => item.trim())
  return normalized.length ? normalized : null
}

function validateQuestion(question: QuestionInput): string {
  if (!question.questionContent) return "请填写题目内容"

  const arrayFields: Array<[string, string[] | null]> = [
    ["评分点", question.rubricPoints],
    ["常见错误", question.commonErrors],
    ["其他解法", question.alternativeSolutions],
    ["分层提示", question.layeredHints],
  ]
  const invalidArrayField = arrayFields.find(([, values]) => values?.some((item) => !item))
  if (invalidArrayField) {
    return `${invalidArrayField[0]}不能包含空白项`
  }
  if (question.guidedQuestions?.some((item) => !item)) {
    return "提示子问题不能包含空白项"
  }
  if (question.rubricPoints && new Set(question.rubricPoints).size !== question.rubricPoints.length) {
    return "评分点不能重复"
  }
  if (question.guidedQuestions && new Set(question.guidedQuestions).size !== question.guidedQuestions.length) {
    return "提示子问题不能重复"
  }
  return ""
}

function submitForm() {
  const question = normalizeQuestion(form)
  validationError.value = validateQuestion(question)
  if (validationError.value) {
    return
  }
  emit("submit", question)
}
</script>

<template>
  <el-form label-position="top" @submit.prevent="submitForm">
    <el-alert
      v-if="validationError || serverError"
      class="form-alert"
      :title="validationError || serverError"
      type="error"
      :closable="false"
      show-icon
    />

    <h2>题目与答案</h2>
    <p class="section-description">题目内容必填；其余内容可随人工补录逐步完善。</p>
    <el-form-item label="题目内容" required>
      <el-input v-model="form.questionContent" type="textarea" :rows="4" />
    </el-form-item>
    <el-form-item label="标准答案">
      <el-input v-model="form.standardAnswer" type="textarea" :rows="3" />
    </el-form-item>

    <h2>评价材料</h2>
    <p class="section-description">评分点非空时使用完整评分规则；其余材料可按需补录。</p>
    <el-form-item label="关键评分点">
      <div class="array-editor">
        <div v-for="(_, index) in form.rubricPoints" :key="`rubric-${index}`" class="array-row">
          <span class="item-index">{{ index + 1 }}</span>
          <el-input v-model="form.rubricPoints[index]" placeholder="必须讲出的关键评分点" />
          <el-button text type="danger" @click="removeArrayItem('rubricPoints', index)">删除</el-button>
        </div>
        <el-button @click="addArrayItem('rubricPoints')">新增评分点</el-button>
      </div>
    </el-form-item>

    <el-form-item label="常见错误">
      <div class="array-editor">
        <div v-for="(_, index) in form.commonErrors" :key="`error-${index}`" class="array-row">
          <span class="item-index">{{ index + 1 }}</span>
          <el-input v-model="form.commonErrors[index]" placeholder="常见错误" />
          <el-button text type="danger" @click="removeArrayItem('commonErrors', index)">删除</el-button>
        </div>
        <el-button @click="addArrayItem('commonErrors')">新增常见错误</el-button>
      </div>
    </el-form-item>

    <el-form-item label="可接受的其他解法">
      <div class="array-editor">
        <div v-for="(_, index) in form.alternativeSolutions" :key="`solution-${index}`" class="array-row">
          <span class="item-index">{{ index + 1 }}</span>
          <el-input v-model="form.alternativeSolutions[index]" placeholder="可接受的其他解法" />
          <el-button text type="danger" @click="removeArrayItem('alternativeSolutions', index)">删除</el-button>
        </div>
        <el-button @click="addArrayItem('alternativeSolutions')">新增其他解法</el-button>
      </div>
    </el-form-item>

    <h2>学习引导</h2>
    <p class="section-description">按从轻到重的顺序填写提示，可选子问题用于引导学生继续思考。</p>
    <el-form-item label="分层提示">
      <div class="array-editor">
        <div v-for="(_, index) in form.layeredHints" :key="`hint-${index}`" class="array-row">
          <span class="item-index">{{ index + 1 }}</span>
          <el-input v-model="form.layeredHints[index]" placeholder="人工录入的分层提示" />
          <el-button text type="danger" @click="removeArrayItem('layeredHints', index)">删除</el-button>
        </div>
        <el-button @click="addArrayItem('layeredHints')">新增分层提示</el-button>
      </div>
    </el-form-item>

    <el-form-item label="提示子问题（可选）">
      <div class="array-editor">
        <div v-for="(_, index) in form.guidedQuestions" :key="`guided-question-${index}`" class="array-row">
          <span class="item-index">{{ index + 1 }}</span>
          <el-input v-model="form.guidedQuestions[index]" placeholder="供大模型参考的提示子问题" />
          <el-button text type="danger" @click="removeArrayItem('guidedQuestions', index)">删除</el-button>
        </div>
        <el-button @click="addArrayItem('guidedQuestions')">新增提示子问题</el-button>
      </div>
    </el-form-item>

    <h2>完整解析</h2>
    <p class="section-description">达到支持上限后向学生展示；未填写时系统仍允许基础自讲。</p>
    <el-form-item label="完整解析">
      <el-input v-model="form.fullSolution" type="textarea" :rows="5" />
    </el-form-item>
    <div class="submit-area"><el-button native-type="submit" type="primary" :loading="submitting">保存题目</el-button></div>
  </el-form>
</template>

<style scoped>
.form-alert {
  margin-bottom: var(--space-6);
}
h2 { margin: var(--space-8) 0 0; font-size: var(--font-size-lg); line-height: 1.45; }
h2:first-of-type { margin-top: 0; }
.section-description { margin: var(--space-1) 0 var(--space-4); color: var(--color-text-muted); font-size: var(--font-size-sm); }

.array-editor {
  display: grid;
  width: 100%;
  gap: var(--space-2);
}

.array-row {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-2);
}
.item-index { display: grid; width: 24px; height: 24px; border-radius: 50%; color: var(--color-brand-700); background: var(--color-brand-50); font-size: 12px; font-weight: 700; place-items: center; }
.submit-area { display: flex; justify-content: flex-end; margin-top: var(--space-8); padding-top: var(--space-6); border-top: 1px solid var(--color-border); }
@media (max-width: 640px) { .array-row { grid-template-columns: 24px minmax(0, 1fr); } .array-row .el-button { grid-column: 2; justify-self: start; } .submit-area .el-button { width: 100%; } }
</style>
