<script setup lang="ts">
withDefaults(defineProps<{
  icon: "submit" | "microphone" | "stop" | "formula"
  label: string
  disabled?: boolean
  loading?: boolean
  type?: "primary" | "danger"
}>(), { disabled: false, loading: false })

defineOptions({ inheritAttrs: false })
</script>

<template>
  <el-tooltip :content="label" :trigger="['hover', 'focus', 'click']" :show-after="200">
    <el-button v-bind="$attrs" class="input-action" :type="type" :disabled="disabled"
      :loading="loading" :aria-label="label" native-type="button">
      <svg v-if="!loading" viewBox="0 0 24 24" width="20" height="20" fill="none"
        stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <template v-if="icon === 'submit'"><path d="m4 12 16-8-6 16-3-6-7-2Z" /><path d="m11 14 9-10" /></template>
        <template v-else-if="icon === 'microphone'"><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11v1a7 7 0 0 0 14 0v-1M12 19v3M8 22h8" /></template>
        <rect v-else-if="icon === 'stop'" x="6" y="6" width="12" height="12" rx="2" />
        <template v-else><path d="M20 5H7l6 7-6 7h13M3 5h1M3 19h1" /></template>
      </svg>
    </el-button>
  </el-tooltip>
</template>

<style scoped>
.input-action.el-button { width: 44px; height: 44px; min-width: 44px; flex: 0 0 44px; margin: 0; padding: 0; border-radius: var(--radius-md); }
.input-action:focus-visible { outline: 3px solid var(--color-focus-ring); outline-offset: 2px; }
</style>
