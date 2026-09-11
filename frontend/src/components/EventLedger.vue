<script setup lang="ts">
import { computed } from "vue"

import type { TrajectoryRecord } from "../types/session-event"

const props = withDefaults(
  defineProps<{
    records: TrajectoryRecord[]
    runLabel: string
    selectedSeq?: number
    collapsed?: boolean
    searchQuery?: string
    hasOlderRecords?: boolean
  }>(),
  {
    selectedSeq: undefined,
    collapsed: false,
    searchQuery: "",
    hasOlderRecords: false,
  },
)

const emit = defineEmits<{
  select: [seq: number]
  toggle: []
  loadOlder: []
}>()

function recordKey(record: TrajectoryRecord): string {
  return `${record.kind}-${record.eventSeq}`
}

const query = computed(() => props.searchQuery.trim().toLowerCase())

function matches(record: TrajectoryRecord): boolean {
  if (query.value === "") return false
  return [record.label, record.summary, record.eventType, `#${record.eventSeq}`]
    .some((value) => value.toLowerCase().includes(query.value))
}

const matchCount = computed(() => props.records.filter(matches).length)

const collapsedSummary = computed(() => {
  const first = props.records[0]
  const last = props.records[props.records.length - 1]
  if (first === undefined || last === undefined) return ""
  return `#${first.eventSeq} ${first.label} … #${last.eventSeq} ${last.label}`
})

function formatDuration(milliseconds: number | undefined): string {
  if (milliseconds === undefined) return ""
  if (milliseconds < 1000) return `${milliseconds} ms`
  return `${(milliseconds / 1000).toFixed(2)} s`
}

function displayTime(value: string): string {
  return new Date(value).toLocaleTimeString("zh-CN", { hour12: false })
}
</script>

<template>
  <div class="ledger" data-trajectory-scroll="">
    <p v-if="query !== ''" class="ledger-search-note" role="status">
      搜索「{{ searchQuery }}」命中 {{ matchCount }} / {{ records.length }} 条记录
    </p>
    <p v-if="hasOlderRecords" class="ledger-more">
      <button type="button" @click="emit('loadOlder')">加载更早的记录</button>
    </p>
    <table class="ledger-table" aria-label="轨迹记录账本">
      <colgroup>
        <col class="event-column" />
        <col class="content-column" />
      </colgroup>
      <tbody>
        <tr
          v-if="collapsed"
          class="group-row"
          tabindex="0"
          @click="emit('toggle')"
          @keydown.enter.prevent="emit('toggle')"
          @keydown.space.prevent="emit('toggle')"
        >
          <td colspan="2">
            <span class="group-ellipsis" aria-hidden="true">…</span>
            <span class="group-text">{{ runLabel }} 已收起 · {{ records.length }} 条记录</span>
            <span class="group-summary">{{ collapsedSummary }}</span>
          </td>
        </tr>
        <tr
          v-for="record in collapsed ? [] : records"
          :key="recordKey(record)"
          class="record-row"
          :class="{ selected: record.eventSeq === selectedSeq, matched: matches(record) }"
          :data-kind="record.kind"
          :data-error="record.status === 'failed' || undefined"
          :data-running="record.status === 'pending' || undefined"
          tabindex="0"
          @click="emit('select', record.eventSeq)"
          @keydown.enter.prevent="emit('select', record.eventSeq)"
          @keydown.space.prevent="emit('select', record.eventSeq)"
        >
          <td class="event-cell">
            <span class="record-index">#{{ record.eventSeq }}</span>
            <span class="kind-tag" :data-kind="record.kind">{{ record.label }}</span>
          </td>
          <td class="content-cell">
            <span class="record-summary" :title="record.summary">{{ record.summary }}</span>
            <span v-if="record.durationMs !== undefined" class="record-duration">
              {{ formatDuration(record.durationMs) }}
            </span>
            <span v-if="record.status === 'failed'" class="record-status failed">失败</span>
            <span v-else-if="record.status === 'pending'" class="record-status pending">等待中</span>
            <time class="record-time">{{ displayTime(record.occurredAt) }}</time>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.ledger { min-width: 0; overflow: hidden; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.ledger-search-note, .ledger-more { margin: 0; padding: var(--space-2) var(--space-4); color: var(--color-text-muted); font-size: var(--font-size-sm); }
.ledger-search-note { border-bottom: 1px solid var(--color-border); }
.ledger-more { border-bottom: 1px solid var(--color-border); }
.ledger-more button { padding: 0; border: none; color: var(--color-brand-700); background: none; cursor: pointer; font: inherit; }
.ledger-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
.event-column { width: 190px; }
.content-column { width: auto; }
.record-row { border-top: 1px solid var(--color-border); cursor: pointer; }
.record-row:first-child, .group-row + .record-row { border-top: none; }
.record-row:hover { background: var(--color-surface-muted); }
.record-row:focus-visible { outline: 2px solid var(--color-brand-600); outline-offset: -2px; }
.record-row.selected { background: var(--color-brand-50); }
.record-row.matched { box-shadow: inset 3px 0 0 var(--color-brand-600); }
.record-row[data-error="true"] { background: var(--color-error-100); }
.event-cell, .content-cell { padding: var(--space-2) var(--space-4); vertical-align: middle; }
.event-cell { display: flex; align-items: center; gap: var(--space-2); border-right: 1px solid var(--color-border); }
.content-cell { display: flex; align-items: center; gap: var(--space-3); min-width: 0; }
.record-index { flex: 0 0 auto; min-width: 38px; color: var(--color-text-muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.kind-tag { flex: 0 0 auto; padding: 2px var(--space-2); border-radius: 999px; color: #ffffff; background: #64748b; font-size: 12px; white-space: nowrap; }
.kind-tag[data-kind="session"] { background: #94a3b8; }
.kind-tag[data-kind="user"] { background: var(--color-brand-700); }
.kind-tag[data-kind="context"] { background: #0ea5e9; }
.kind-tag[data-kind="model_request"] { background: #7c3aed; }
.kind-tag[data-kind="model_response"] { background: #16a34a; }
.kind-tag[data-kind="model_error"] { background: #dc2626; }
.kind-tag[data-kind="state_change"] { background: #d97706; }
.record-summary { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.record-duration, .record-time { flex: 0 0 auto; color: var(--color-text-muted); font-size: var(--font-size-sm); }
.record-time { min-width: 68px; text-align: right; }
.record-status { flex: 0 0 auto; padding: 1px var(--space-2); border-radius: var(--radius-sm); font-size: 12px; }
.record-status.failed { color: var(--color-error-700); background: var(--color-error-100); }
.record-status.pending { color: var(--color-text-secondary); background: var(--color-surface-muted); }
.group-row { cursor: pointer; background: var(--color-surface-muted); }
.group-row td { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) var(--space-4); }
.group-row:focus-visible { outline: 2px solid var(--color-brand-600); outline-offset: -2px; }
.group-ellipsis { color: var(--color-text-muted); }
.group-text { color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.group-summary { min-width: 0; overflow: hidden; color: var(--color-text-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 640px) {
  .event-column { width: 132px; }
  .event-cell, .content-cell { padding: var(--space-2) var(--space-3); }
  .record-time { display: none; }
}
</style>
