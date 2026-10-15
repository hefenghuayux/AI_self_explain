<script setup lang="ts">
withDefaults(defineProps<{
  pending?: boolean
  blocks?: Array<{ key: string; label?: string; text: string }>
  error?: string
}>(), { pending: false, blocks: () => [] })
</script>

<template>
  <div class="teacher-reply-card" :aria-busy="pending" aria-live="polite">
    <div class="teacher-reply-card__heading">
      <slot name="controls" />
      <strong>老师回复</strong>
      <span v-if="pending" class="teacher-reply-card__status" role="status">正在生成…</span>
    </div>
    <p v-if="error" class="teacher-reply-card__error" role="alert">{{ error }}</p>
    <template v-else>
      <p v-for="block in blocks" :key="block.key" class="teacher-reply-card__text"><strong v-if="block.label">{{ block.label }}：</strong>{{ block.text }}</p>
      <el-skeleton v-if="pending && !blocks.length" :rows="3" animated aria-label="正在生成老师回复" />
    </template>
    <slot />
  </div>
</template>

<style scoped>
.teacher-reply-card { min-width: 0; padding: var(--space-4); border: 1px solid var(--color-brand-100); border-left: 3px solid var(--color-brand-600); border-radius: var(--radius-lg); background: var(--color-brand-50); overflow-wrap: anywhere; }
.teacher-reply-card__heading { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); margin-bottom: var(--space-3); }
.teacher-reply-card__status { color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.teacher-reply-card__text { margin: var(--space-2) 0 0; white-space: pre-wrap; line-height: 1.75; }
.teacher-reply-card__error { margin: 0; color: var(--color-error-700); }
@media (prefers-reduced-motion: reduce) {
  :deep(.el-skeleton.is-animated .el-skeleton__item) { animation: none; }
}
</style>
