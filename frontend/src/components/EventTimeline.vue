<script setup lang="ts">
import { computed } from "vue"

import type { TrajectoryRecord } from "../types/session-event"

type TimelineMode = "sequence" | "duration"

const props = withDefaults(
  defineProps<{
    records: TrajectoryRecord[]
    mode?: TimelineMode
    selectedSeq?: number
  }>(),
  { mode: "sequence", selectedSeq: undefined },
)

const emit = defineEmits<{
  select: [seq: number]
}>()

interface TimelineBlock {
  record: TrajectoryRecord
  widthPercent: number
}

function elapsedMs(record: TrajectoryRecord, previous: TrajectoryRecord | undefined): number {
  if (previous === undefined) return 0
  const gap = new Date(record.occurredAt).getTime() - new Date(previous.occurredAt).getTime()
  return Number.isFinite(gap) && gap > 0 ? gap : 0
}

const blocks = computed<TimelineBlock[]>(() => {
  if (props.mode === "sequence") {
    const width = props.records.length === 0 ? 0 : 100 / props.records.length
    return props.records.map((record) => ({ record, widthPercent: width }))
  }
  const gaps = props.records.map((record, index) => elapsedMs(record, props.records[index - 1]))
  const total = gaps.reduce((sum, gap) => sum + gap, 0)
  if (total === 0) {
    const width = props.records.length === 0 ? 0 : 100 / props.records.length
    return props.records.map((record) => ({ record, widthPercent: width }))
  }
  return props.records.map((record, index) => ({
    record,
    widthPercent: Math.max((gaps[index] ?? 0) / total * 100, 0.5),
  }))
})

const summary = computed(() => {
  const start = props.records[0]
  const end = props.records[props.records.length - 1]
  if (start === undefined || end === undefined) return "无记录"
  const span = new Date(end.occurredAt).getTime() - new Date(start.occurredAt).getTime()
  return `${props.records.length} 条记录 · 跨度 ${formatSpan(span)}`
})

function formatSpan(milliseconds: number): string {
  if (!Number.isFinite(milliseconds) || milliseconds <= 0) return "0 ms"
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`
  return `${(milliseconds / 1000).toFixed(2)} s`
}

function blockLabel(record: TrajectoryRecord): string {
  const duration = record.durationMs === undefined ? "" : ` · 耗时 ${record.durationMs} ms`
  return `#${record.eventSeq} ${record.label}${duration}\n${new Date(record.occurredAt).toLocaleString("zh-CN", { hour12: false })}`
}
</script>

<template>
  <section class="timeline" aria-label="轨迹时间线">
    <header class="timeline-header">
      <span class="timeline-summary">{{ summary }}</span>
      <span class="timeline-hint">点击色块定位记录</span>
    </header>
    <div class="timeline-track" role="list">
      <button
        v-for="block in blocks"
        :key="block.record.eventSeq"
        type="button"
        role="listitem"
        class="timeline-block"
        :class="[`timeline-block--${mode}`, { active: block.record.eventSeq === selectedSeq }]"
        :data-kind="block.record.kind"
        :style="{ '--block-width': `${block.widthPercent}%` }"
        :title="blockLabel(block.record)"
        @click="emit('select', block.record.eventSeq)"
      />
    </div>
  </section>
</template>

<style scoped>
.timeline { padding: var(--space-3) var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.timeline-header { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-2); }
.timeline-summary { color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.timeline-hint { color: var(--color-text-muted); font-size: 12px; }
.timeline-track { display: flex; gap: 1px; height: 26px; padding: 2px; border-radius: var(--radius-sm); background: var(--color-surface-muted); }
.timeline-block { flex: 0 0 auto; width: var(--block-width); min-width: 3px; padding: 0; border: none; border-radius: 2px; background: var(--color-brand-600); cursor: pointer; }
/* 等宽模式让 flex 分配宽度，避免百分比宽度与 gap 累积后右侧留白。 */
.timeline-block--sequence { flex: 1 1 0; width: auto; }
.timeline-block:hover { filter: brightness(1.15); }
.timeline-block.active { outline: 2px solid var(--color-text-primary); outline-offset: 1px; }
.timeline-block[data-kind="session"] { background: #94a3b8; }
.timeline-block[data-kind="user"] { background: var(--color-brand-700); }
.timeline-block[data-kind="context"] { background: #0ea5e9; }
.timeline-block[data-kind="model_request"] { background: #7c3aed; }
.timeline-block[data-kind="model_response"] { background: #16a34a; }
.timeline-block[data-kind="model_error"] { background: #dc2626; }
.timeline-block[data-kind="state_change"] { background: #d97706; }
@media (max-width: 640px) {
  .timeline-header { align-items: flex-start; flex-direction: column; gap: var(--space-1); }
}
</style>
