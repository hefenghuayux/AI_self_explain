<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import "mathlive"
import "mathlive/fonts.css"
import type { MathfieldElement } from "mathlive"
import { renderStudentTextHtml } from "../utils/studentTextHtml"

const props = withDefaults(defineProps<{
  modelValue: string
  disabled: boolean
  testId?: string
  placeholder?: string
  label?: string
}>(), {
  testId: "current-step-content",
  placeholder: "输入关键步骤或解题过程",
  label: "关键步骤或解题过程输入",
})
const emit = defineEmits<{ "update:modelValue": [value: string] }>()
const editorRef = ref<HTMLDivElement>()
let savedRange: Range | null = null
let activeFormula: HTMLSpanElement | null = null
let activeMathField: MathfieldElement | null = null

function serialize(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent || ""
  if (!(node instanceof HTMLElement)) return ""
  if (node.dataset.formula !== undefined) {
    const latex = node === activeFormula ? activeMathField!.value : node.dataset.formula
    return latex ? `\\(${latex}\\)` : ""
  }
  if (node.tagName === "BR") return "\n"
  return Array.from(node.childNodes).map((child, index) => {
    const block = child instanceof HTMLElement && ["DIV", "P"].includes(child.tagName)
    return `${block && index > 0 ? "\n" : ""}${serialize(child)}`
  }).join("")
}

function updateValue() {
  if (editorRef.value) emit("update:modelValue", serialize(editorRef.value))
}

function createFormula(latex: string) {
  const formula = document.createElement("span")
  formula.className = "step-formula"
  formula.contentEditable = "false"
  formula.dataset.formula = latex
  formula.setAttribute("aria-label", "编辑公式")
  formula.innerHTML = renderStudentTextHtml(`\\(${latex}\\)`)
  return formula
}

function renderValue(value: string) {
  const editor = editorRef.value
  if (!editor) return
  editor.replaceChildren()
  let textStart = 0
  for (const match of value.matchAll(/\\\(([\s\S]*?)\\\)/g)) {
    editor.append(document.createTextNode(value.slice(textStart, match.index)))
    editor.append(createFormula(match[1]))
    textStart = match.index! + match[0].length
  }
  editor.append(document.createTextNode(value.slice(textStart)))
  savedRange = null
}

function rememberSelection() {
  const selection = window.getSelection()
  if (!selection?.rangeCount || !editorRef.value) return
  const range = selection.getRangeAt(0)
  if (editorRef.value.contains(range.startContainer) && editorRef.value.contains(range.endContainer)
    && !activeFormula?.contains(range.startContainer)) savedRange = range.cloneRange()
}

function finishFormula() {
  const formula = activeFormula
  const mathField = activeMathField
  if (!formula || !mathField) return
  const latex = mathField.value
  activeFormula = null
  activeMathField = null
  if (latex) {
    formula.dataset.formula = latex
    formula.innerHTML = renderStudentTextHtml(`\\(${latex}\\)`)
  } else formula.remove()
  window.mathVirtualKeyboard?.hide({ animate: false })
  updateValue()
}

async function focusFormula(formula: HTMLSpanElement) {
  if (props.disabled) return
  if (activeFormula === formula) {
    activeMathField!.focus()
    window.mathVirtualKeyboard?.show({ animate: false })
    return
  }
  finishFormula()
  const mathField = document.createElement("math-field") as MathfieldElement
  mathField.value = formula.dataset.formula || ""
  activeFormula = formula
  activeMathField = mathField
  formula.replaceChildren(mathField)
  mathField.addEventListener("input", updateValue)
  mathField.addEventListener("blur", () => {
    if (activeMathField === mathField) finishFormula()
  })
  mathField.addEventListener("move-out", (event) => {
    event.preventDefault()
    const direction = (event as CustomEvent<{ direction: string }>).detail.direction
    const range = document.createRange()
    if (direction === "backward") range.setStartBefore(formula)
    else range.setStartAfter(formula)
    range.collapse(true)
    finishFormula()
    editorRef.value!.focus()
    const selection = window.getSelection()!
    selection.removeAllRanges()
    selection.addRange(range)
    savedRange = range.cloneRange()
  })
  await customElements.whenDefined("math-field")
  await nextTick()
  await new Promise<void>((resolve) => window.setTimeout(resolve, 0))
  mathField.mathVirtualKeyboardPolicy = "manual"
  mathField.menuItems = []
  mathField.focus()
  window.mathVirtualKeyboard?.show({ animate: false })
}

function open() {
  if (props.disabled || !editorRef.value) return
  if (activeFormula) return focusFormula(activeFormula)
  const editor = editorRef.value
  const range = savedRange?.cloneRange() || document.createRange()
  if (!savedRange || !editor.contains(range.startContainer) || !editor.contains(range.endContainer)) {
    range.selectNodeContents(editor)
    range.collapse(false)
  }
  range.deleteContents()
  const formula = createFormula("")
  range.insertNode(formula)
  range.setStartAfter(formula)
  range.collapse(true)
  savedRange = range.cloneRange()
  void focusFormula(formula)
  updateValue()
}

function handleClick(event: MouseEvent) {
  const formula = (event.target as HTMLElement).closest<HTMLSpanElement>(".step-formula")
  if (formula && editorRef.value?.contains(formula)) void focusFormula(formula)
}

function handlePaste(event: ClipboardEvent) {
  event.preventDefault()
  if (props.disabled) return
  rememberSelection()
  const selection = window.getSelection()
  if (!selection?.rangeCount) return
  const range = selection.getRangeAt(0)
  if (!editorRef.value?.contains(range.commonAncestorContainer)) return
  range.deleteContents()
  const text = document.createTextNode(event.clipboardData!.getData("text/plain"))
  range.insertNode(text)
  range.setStartAfter(text)
  range.collapse(true)
  selection.removeAllRanges()
  selection.addRange(range)
  rememberSelection()
  updateValue()
}

function handleKeyboardToggle() {
  if (activeMathField && window.mathVirtualKeyboard && !window.mathVirtualKeyboard.visible) finishFormula()
}

watch(() => props.modelValue, (value) => {
  if (editorRef.value && serialize(editorRef.value) !== value) {
    finishFormula()
    renderValue(value)
  }
})
watch(() => props.disabled, (disabled) => { if (disabled) finishFormula() })
onMounted(() => {
  renderValue(props.modelValue)
  document.addEventListener("selectionchange", rememberSelection)
  window.mathVirtualKeyboard?.addEventListener("virtual-keyboard-toggle", handleKeyboardToggle)
})
onBeforeUnmount(() => {
  document.removeEventListener("selectionchange", rememberSelection)
  window.mathVirtualKeyboard?.removeEventListener("virtual-keyboard-toggle", handleKeyboardToggle)
  if (activeMathField) window.mathVirtualKeyboard?.hide({ animate: false })
})
defineExpose({ open })
</script>

<template>
  <div ref="editorRef" class="step-content-input" :contenteditable="!disabled"
    :aria-disabled="disabled" :data-testid="testId" :data-placeholder="placeholder"
    :aria-label="label" role="textbox" aria-multiline="true"
    @input="updateValue" @click="handleClick" @paste="handlePaste"
    @keyup="rememberSelection" @mouseup="rememberSelection" />
</template>

<style scoped>
.step-content-input { box-sizing: border-box; width: 100%; min-width: 0; min-height: 128px; padding: var(--space-3); border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); color: var(--color-text-primary); background: var(--color-surface); font-size: var(--font-size-base); line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.step-content-input:empty::before { content: attr(data-placeholder); color: var(--color-text-secondary); pointer-events: none; }
.step-content-input:focus-within { border-color: var(--color-brand-600); outline: 3px solid var(--color-focus-ring); outline-offset: 2px; }
.step-content-input[aria-disabled="true"] { color: var(--color-text-secondary); background: var(--color-surface-muted); cursor: not-allowed; }
.step-content-input :deep(.step-formula) { display: inline-block; cursor: pointer; vertical-align: baseline; max-width: 100%; }
.step-content-input :deep(math-field) { min-width: 2em; max-width: 100%; padding: 0; border: 0; background: transparent; font-size: 1.1em; }
.step-content-input :deep(math-field::part(virtual-keyboard-toggle)),
.step-content-input :deep(math-field::part(menu-toggle)) { display: none; }
</style>
