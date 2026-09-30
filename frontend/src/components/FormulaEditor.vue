<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from "vue"
import "mathlive"
import "mathlive/fonts.css"
import type { MathfieldElement } from "mathlive"

const emit = defineEmits<{
  confirmed: [latex: string]
}>()

const editorVisible = ref(false)
const value = ref("")
const errorMessage = ref("")
const mathFieldRef = ref<MathfieldElement | null>(null)

async function open(initialValue = "") {
  value.value = initialValue
  errorMessage.value = ""
  editorVisible.value = true
  await nextTick()
  const mathField = mathFieldRef.value
  if (!mathField) return
  mathField.value = initialValue
  mathField.focus()
  window.mathVirtualKeyboard?.show({ animate: false })
}

function clear() {
  value.value = ""
  errorMessage.value = ""
  if (mathFieldRef.value) mathFieldRef.value.value = ""
}

function close() {
  editorVisible.value = false
  window.mathVirtualKeyboard?.hide({ animate: false })
  clear()
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
  close()
}

function cancel() {
  close()
}

onBeforeUnmount(() => {
  window.mathVirtualKeyboard?.hide({ animate: false })
})

defineExpose({ clear, open, value, editorVisible })
</script>

<template>
  <div v-if="editorVisible" class="formula-editor" data-testid="formula-editor">
    <math-field
      ref="mathFieldRef"
      class="formula-editor-field"
      :value="value"
      virtual-keyboard-mode="manual"
      @input="handleInput"
    />
    <p v-if="errorMessage" class="formula-editor-error" role="alert">{{ errorMessage }}</p>
    <div class="formula-editor-actions">
      <el-button data-testid="cancel-formula" @click="cancel">取消</el-button>
      <el-button data-testid="confirm-formula" type="primary" @click="confirm">插入</el-button>
    </div>
  </div>
</template>

<style scoped>
.formula-editor {
  margin-top: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface-subtle);
}

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

.formula-editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
</style>
