<script setup lang="ts">
import { nextTick, ref } from "vue"
import "mathlive"
import "mathlive/fonts.css"
import type { MathfieldElement } from "mathlive"

const emit = defineEmits<{
  confirmed: [latex: string]
}>()

const dialogVisible = ref(false)
const value = ref("")
const errorMessage = ref("")
const mathFieldRef = ref<MathfieldElement | null>(null)

async function open(initialValue = "") {
  value.value = initialValue
  errorMessage.value = ""
  dialogVisible.value = true
  await nextTick()
  mathFieldRef.value?.focus()
}

function clear() {
  value.value = ""
  errorMessage.value = ""
  if (mathFieldRef.value) mathFieldRef.value.value = ""
}

function handleInput(event: Event) {
  value.value = (event.target as MathfieldElement).value
  errorMessage.value = ""
}

function confirm() {
  const latex = value.value.trim()
  if (!latex) {
    errorMessage.value = "请输入公式后再确认"
    return
  }
  emit("confirmed", value.value)
  dialogVisible.value = false
  clear()
}

function cancel() {
  dialogVisible.value = false
  clear()
}

defineExpose({ clear, open, value })
</script>

<template>
  <el-dialog
    v-model="dialogVisible"
    title="插入公式"
    width="min(640px, calc(100vw - 32px))"
    :close-on-click-modal="false"
    @closed="clear"
  >
    <math-field
      ref="mathFieldRef"
      class="formula-editor-field"
      :value="value"
      virtual-keyboard-mode="onfocus"
      @input="handleInput"
    />
    <p v-if="errorMessage" class="formula-editor-error" role="alert">{{ errorMessage }}</p>
    <template #footer>
      <el-button data-testid="cancel-formula" @click="cancel">取消</el-button>
      <el-button data-testid="confirm-formula" type="primary" @click="confirm">插入</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.formula-editor-field {
  display: block;
  width: 100%;
  min-height: 56px;
  padding: var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  font-size: 1.25rem;
}

.formula-editor-error {
  margin: var(--space-2) 0 0;
  color: var(--color-error-700);
}
</style>
