<script setup lang="ts">
import { computed, ref } from "vue"

import { formatDuration, formatTime } from "../utils/trajectoryTime"
import type { TrajectoryRecord, TrajectoryRecordKind } from "../types/session-event"

type LedgerScope = "core" | "all"

/** 精简范围：只保留上下文、用户与助手（模型）信息，隐藏状态变化和模型请求。 */
const CORE_KINDS: readonly TrajectoryRecordKind[] = ["session", "user", "context", "model_response", "model_error"]

const props = withDefaults(
  defineProps<{
    records: TrajectoryRecord[]
    runLabel: string
    scope?: LedgerScope
    selectedSeq?: number
    collapsed?: boolean
    searchQuery?: string
    hasOlderRecords?: boolean
  }>(),
  {
    scope: "core",
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

const expandedSeqs = ref<ReadonlySet<number>>(new Set())

function recordKey(record: TrajectoryRecord): string {
  return `${record.kind}-${record.eventSeq}`
}

const query = computed(() => props.searchQuery.trim().toLowerCase())

function matches(record: TrajectoryRecord): boolean {
  if (query.value === "") return false
  return [record.label, record.summary, record.eventType, `#${record.eventSeq}`]
    .some((value) => value.toLowerCase().includes(query.value))
}

const scopedRecords = computed<TrajectoryRecord[]>(() =>
  props.scope === "core"
    ? props.records.filter((record) => CORE_KINDS.includes(record.kind))
    : props.records,
)

const hiddenCount = computed(() => props.records.length - scopedRecords.value.length)
const matchCount = computed(() => scopedRecords.value.filter(matches).length)

const collapsedSummary = computed(() => {
  const first = scopedRecords.value[0]
  const last = scopedRecords.value[scopedRecords.value.length - 1]
  if (first === undefined || last === undefined) return ""
  return `#${first.eventSeq} ${first.label} … #${last.eventSeq} ${last.label}`
})

function isExpanded(seq: number): boolean {
  return expandedSeqs.value.has(seq)
}

function toggleExpand(seq: number) {
  const next = new Set(expandedSeqs.value)
  if (next.has(seq)) next.delete(seq)
  else next.add(seq)
  expandedSeqs.value = next
}

function scopeHint(): string {
  return `${scopedRecords.value.length} / ${props.records.length} 条记录可见`
}
</script>

<template>
  <div class="ledger" data-trajectory-scroll="">
    <p v-if="query !== ''" class="ledger-note" role="status">
      搜索「{{ searchQuery }}」命中 {{ matchCount }} / {{ scopedRecords.length }} 条记录
    </p>
    <p v-if="scope === 'core' && hiddenCount > 0" class="ledger-note">
      {{ scopeHint() }}；已按精简范围隐藏 {{ hiddenCount }} 条状态变化与模型请求记录。
    </p>
    <p v-if="hasOlderRecords" class="ledger-note">
      <button type="button" class="link-button" @click="emit('loadOlder')">加载更早的记录</button>
    </p>

    <div class="ledger-head" aria-hidden="true">
      <span>事件</span>
      <span>内容</span>
    </div>

    <div class="ledger-body">
      <div
        v-if="collapsed"
        class="group-row"
        tabindex="0"
        role="button"
        @click="emit('toggle')"
        @keydown.enter.prevent="emit('toggle')"
        @keydown.space.prevent="emit('toggle')"
      >
        <span class="group-ellipsis" aria-hidden="true">…</span>
        <span class="group-text">{{ runLabel }} 已收起 · 当前范围 {{ scopedRecords.length }} 条记录</span>
        <span class="group-summary">{{ collapsedSummary }}</span>
      </div>
      <template v-else>
        <div
          v-for="record in scopedRecords"
          :key="recordKey(record)"
          class="record-row"
          :class="{ selected: record.eventSeq === selectedSeq, matched: matches(record), expanded: isExpanded(record.eventSeq) }"
          :data-kind="record.kind"
          :data-error="record.status === 'failed' || undefined"
          :data-running="record.status === 'pending' || undefined"
          tabindex="0"
          @click="emit('select', record.eventSeq)"
          @keydown.enter.prevent="emit('select', record.eventSeq)"
          @keydown.space.prevent="emit('select', record.eventSeq)"
        >
          <div class="event-cell">
            <span class="record-index">#{{ record.eventSeq }}</span>
            <span class="kind-tag" :data-kind="record.kind">{{ record.label }}</span>
          </div>
          <div class="content-cell">
            <span v-if="!isExpanded(record.eventSeq)" class="record-summary" :title="record.summary">{{ record.summary }}</span>
            <span v-if="!isExpanded(record.eventSeq)" class="record-duration">
              {{ formatDuration(record.durationMs) }}
            </span>
            <span v-if="record.status === 'failed'" class="record-status failed">失败</span>
            <span v-else-if="record.status === 'pending'" class="record-status pending">等待中</span>
            <time class="record-time" :datetime="record.occurredAt">{{ formatTime(record.occurredAt) }}</time>
            <button
              type="button"
              class="expand-button"
              :aria-expanded="isExpanded(record.eventSeq)"
              :aria-label="isExpanded(record.eventSeq) ? `收起记录 #${record.eventSeq}` : `展开记录 #${record.eventSeq}`"
              @click.stop="toggleExpand(record.eventSeq)"
            >
              {{ isExpanded(record.eventSeq) ? "收起" : "展开" }}
            </button>
          </div>
          <!-- 展开区跨两列铺满，直接显示未压缩的完整原文，保留 JSON 缩进与换行。 -->
          <pre v-if="isExpanded(record.eventSeq)" class="record-full">{{ record.fullText }}</pre>
        </div>
        <p v-if="scopedRecords.length === 0" class="empty-state">
          当前范围内没有可展示的记录；可在工具栏切换为「完整」查看模型请求与状态变化。
        </p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.ledger { min-width: 0; overflow: hidden; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.ledger-note { margin: 0; padding: var(--space-2) var(--space-4); border-bottom: 1px solid var(--color-border); color: var(--color-text-muted); font-size: var(--font-size-sm); }
.link-button { padding: 0; border: none; color: var(--color-brand-700); background: none; cursor: pointer; font: inherit; }
/* 用 grid 而不是 table：td 上挂 display:flex 会破坏表格列算法，把内容列压成 0 宽。 */
.ledger-head, .record-row, .group-row { display: grid; grid-template-columns: 190px minmax(0, 1fr); }
.ledger-head { border-bottom: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 12px; }
.ledger-head span { padding: var(--space-2) var(--space-4); }
.ledger-body { display: block; }
.record-row { border-top: 1px solid var(--color-border); cursor: pointer; }
.record-row:first-child { border-top: none; }
.record-row:hover { background: var(--color-surface-muted); }
.record-row:focus-visible { outline: 2px solid var(--color-brand-600); outline-offset: -2px; }
.record-row.selected { background: var(--color-brand-50); }
.record-row.matched { box-shadow: inset 3px 0 0 var(--color-brand-600); }
.record-row[data-error="true"] { background: var(--color-error-100); }
.record-row.expanded { background: var(--color-surface-muted); }
.event-cell, .content-cell { padding: var(--space-2) var(--space-4); }
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
.record-summary { flex: 1 1 auto; min-width: 0; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* 展开区跨满两列，按原文换行显示完整内容（JSON 缩进因此在界面上保留）。 */
.record-full { grid-column: 1 / -1; max-height: 480px; overflow: auto; margin: 0; padding: var(--space-3) var(--space-4) var(--space-4); border-top: 1px dashed var(--color-border); color: var(--color-text-primary); background: var(--color-surface); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
.record-duration, .record-time { flex: 0 0 auto; color: var(--color-text-muted); font-size: var(--font-size-sm); }
.record-time { min-width: 68px; text-align: right; }
.record-status { flex: 0 0 auto; padding: 1px var(--space-2); border-radius: var(--radius-sm); font-size: 12px; }
.record-status.failed { color: var(--color-error-700); background: var(--color-error-100); }
.record-status.pending { color: var(--color-text-secondary); background: var(--color-surface-muted); }
.expand-button { flex: 0 0 auto; padding: 1px var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-sm); color: var(--color-text-secondary); background: var(--color-surface); cursor: pointer; font: inherit; font-size: 12px; }
.expand-button:hover { border-color: var(--color-brand-700); color: var(--color-brand-700); }
.group-row { cursor: pointer; background: var(--color-surface-muted); }
.group-row:focus-visible { outline: 2px solid var(--color-brand-600); outline-offset: -2px; }
.group-row > * { display: inline-flex; align-items: center; padding: var(--space-2) 0; }
.group-ellipsis { padding-left: var(--space-4); color: var(--color-text-muted); }
.group-text { color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.group-summary { min-width: 0; overflow: hidden; color: var(--color-text-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.empty-state { margin: 0; padding: var(--space-4); color: var(--color-text-muted); }
@media (max-width: 640px) {
  .ledger-head, .record-row, .group-row { grid-template-columns: 128px minmax(0, 1fr); }
  .event-cell, .content-cell { padding: var(--space-2) var(--space-3); }
  .record-time { display: none; }
}
</style>
