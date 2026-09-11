<script setup lang="ts">
import { computed } from "vue"

interface JsonEntry {
  key: string
  value: unknown
}

const props = withDefaults(
  defineProps<{
    value: unknown
    depth?: number
    maxDepth?: number
  }>(),
  { depth: 0, maxDepth: 6 },
)

function isContainer(value: unknown): value is Record<string, unknown> | unknown[] {
  return typeof value === "object" && value !== null
}

function entriesOf(value: Record<string, unknown> | unknown[]): JsonEntry[] {
  if (Array.isArray(value)) {
    return value.map((item, index) => ({ key: String(index), value: item }))
  }
  return Object.entries(value).map(([key, item]) => ({ key, value: item }))
}

const entries = computed<JsonEntry[]>(() =>
  isContainer(props.value) ? entriesOf(props.value) : [],
)

function scalarText(value: unknown): string {
  if (value === null) return "null"
  if (typeof value === "string") return value === "" ? '""' : value
  if (typeof value === "boolean") return value ? "true" : "false"
  return String(value)
}

function scalarClass(value: unknown): string {
  if (value === null) return "json-null"
  if (typeof value === "string") return "json-string"
  if (typeof value === "number") return "json-number"
  if (typeof value === "boolean") return "json-boolean"
  return "json-other"
}

function containerLabel(value: Record<string, unknown> | unknown[]): string {
  return Array.isArray(value) ? `${value.length} 项` : `${Object.keys(value).length} 个字段`
}
</script>

<template>
  <div v-if="isContainer(value)" class="json-node">
    <details v-if="depth < maxDepth" open>
      <summary>
        <span class="json-bracket">{{ Array.isArray(value) ? "[" : "{" }}</span>
        <span class="json-count">{{ containerLabel(value as Record<string, unknown> | unknown[]) }}</span>
      </summary>
      <ul class="json-list">
        <li v-for="entry in entries" :key="entry.key" class="json-item">
          <span class="json-key">{{ entry.key }}</span>
          <span class="json-colon">:</span>
          <JsonTree
            v-if="isContainer(entry.value)"
            :value="entry.value"
            :depth="depth + 1"
            :max-depth="maxDepth"
          />
          <span v-else :class="scalarClass(entry.value)">{{ scalarText(entry.value) }}</span>
        </li>
      </ul>
    </details>
    <pre v-else class="json-truncated">{{ JSON.stringify(value, null, 2) }}</pre>
  </div>
  <span v-else :class="scalarClass(value)">{{ scalarText(value) }}</span>
</template>

<style scoped>
.json-node { min-width: 0; }
.json-node details { margin: 0; }
.json-node summary { display: inline-flex; gap: var(--space-2); align-items: center; cursor: pointer; color: var(--color-text-secondary); }
.json-bracket { color: var(--color-text-muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.json-count { color: var(--color-text-muted); font-size: var(--font-size-sm); }
.json-list { display: grid; gap: var(--space-1); margin: var(--space-2) 0 0; padding-left: var(--space-4); border-left: 1px solid var(--color-border); list-style: none; }
.json-item { display: flex; gap: var(--space-2); align-items: flex-start; min-width: 0; }
.json-key { flex: 0 0 auto; color: var(--color-brand-700); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.json-colon { color: var(--color-text-muted); }
.json-string { overflow-wrap: anywhere; white-space: pre-wrap; }
.json-number { color: #b45309; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.json-boolean { color: #7c3aed; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.json-null { color: var(--color-text-muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.json-other { overflow-wrap: anywhere; }
.json-truncated { max-height: 240px; overflow: auto; margin: var(--space-2) 0 0; padding: var(--space-3); border-radius: var(--radius-sm); color: #e5e7eb; background: #1f2937; font-size: 12px; white-space: pre-wrap; }
</style>
