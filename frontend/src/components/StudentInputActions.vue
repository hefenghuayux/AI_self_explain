<script setup lang="ts">
import InputActionButton from "./InputActionButton.vue"

defineProps<{
  submitTestId: string
  formulaTestId: string
  submitDisabled: boolean
  formulaDisabled: boolean
  loading?: boolean
}>()
defineEmits<{ submit: []; formula: [] }>()
</script>

<template>
  <div class="student-input-actions" role="group" aria-label="输入操作">
    <slot name="before" />
    <InputActionButton icon="submit" label="提交" type="primary" :data-testid="submitTestId"
      :disabled="submitDisabled" :loading="loading" @click="$emit('submit')" />
    <slot name="voice" />
    <InputActionButton icon="formula" label="插入公式" :data-testid="formulaTestId"
      :disabled="formulaDisabled" @click="$emit('formula')" />
    <div v-if="$slots.after" class="supplementary-actions"><slot name="after" /></div>
  </div>
</template>

<style scoped>
.student-input-actions { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-4); }
.supplementary-actions { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); margin-left: var(--space-2); }
.supplementary-actions :deep(.el-button) { margin: 0; }
</style>
