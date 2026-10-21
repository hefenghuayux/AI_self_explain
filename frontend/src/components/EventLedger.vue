<script setup lang="ts">
import { computed, ref } from "vue"

import { formatCacheHitRate, type DeepSeekCacheUsage } from "../utils/deepseekCache"
import { formatDuration, formatTime } from "../utils/trajectoryTime"
import { scopeRecords, type TrajectoryScope } from "../utils/trajectoryScope"
import type { TrajectoryRecord } from "../types/session-event"

const props = withDefaults(
  defineProps<{
    records: TrajectoryRecord[]
    runLabel: string
    scope?: TrajectoryScope
    selectedSeq?: number
    collapsed?: boolean
    searchQuery?: string
    hasOlderRecords?: boolean
    /** 当前运行的 DeepSeek 缓存用量；非 DeepSeek 或未返回缓存字段时为 undefined。 */
    cacheUsage?: DeepSeekCacheUsage
  }>(),
  {
    scope: "core",
    selectedSeq: undefined,
    collapsed: false,
    searchQuery: "",
    hasOlderRecords: false,
    cacheUsage: undefined,
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

const scopedRecords = computed(() => scopeRecords(props.records, props.scope))

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

/** 表头右上角两行：第一行缓存命中口径，第二行模型、输入输出 token 与调用次数。 */
const cacheLines = computed(() => {
  const usage = props.cacheUsage
  if (usage === undefined) return undefined
  return {
    cache: `DeepSeek 缓存命中 ${formatCacheHitRate(usage)}（命中 ${usage.hitTokens} · 未命中 ${usage.missTokens} tok）`,
    tokens: `${usage.models.join(" · ")} · 输入 ${usage.inputTokens} tok · 输出 ${usage.outputTokens} tok · ${usage.callCount} 次调用`,
  }
})

/** 3 万字符级的正文靠人工选中复制不现实，展开区提供复制全文。 */
const copiedSeq = ref<number>()
const copyErrorSeq = ref<number>()

/**
 * 展开区展示的正文。
 *
 * 正常情况下就是后端给的完整原文；当后端是缺少 fullText 的旧版本时退回摘要，
 * 这样展开至少能看到内容，而不是因为 undefined.length 打断整次渲染。
 */
function expandText(record: TrajectoryRecord): string {
  return record.fullText ?? record.summary
}

/** 只有拿到完整原文时才提供复制，避免把被截断的摘要当成全文复制走。 */
function hasFullText(record: TrajectoryRecord): boolean {
  return typeof record.fullText === "string" && record.fullText !== ""
}

async function copyFullText(record: TrajectoryRecord) {
  copyErrorSeq.value = undefined
  try {
    await navigator.clipboard.writeText(expandText(record))
    copiedSeq.value = record.eventSeq
  } catch {
    copyErrorSeq.value = record.eventSeq
  }
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

    <div class="ledger-head">
      <span class="head-cell" aria-hidden="true">事件</span>
      <span class="head-cell" aria-hidden="true">内容</span>
      <p v-if="cacheLines" class="head-cache">
        <span>{{ cacheLines.cache }}</span>
        <span>{{ cacheLines.tokens }}</span>
      </p>
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
          <div v-if="isExpanded(record.eventSeq)" class="record-full-block">
            <div class="record-full-bar">
              <span v-if="hasFullText(record)" class="record-full-size">
                {{ expandText(record).length }} 字符
              </span>
              <span v-else class="record-full-size">后端未返回完整原文，以下为摘要</span>
              <button
                v-if="hasFullText(record)"
                type="button"
                class="copy-button"
                :aria-label="`复制记录 #${record.eventSeq} 的全文`"
                @click.stop="copyFullText(record)"
              >
                {{ copiedSeq === record.eventSeq ? "已复制" : "复制全文" }}
              </button>
              <span v-if="copyErrorSeq === record.eventSeq" class="copy-error">复制失败，请手动选中</span>
            </div>
            <pre class="record-full">{{ expandText(record) }}</pre>
          </div>
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
.record-row, .group-row { display: grid; grid-template-columns: 190px minmax(0, 1fr); }
/* 表头用 flex：右侧还要放 DeepSeek 用量，继续用 grid 会新开一列，把「内容」标签挤得与记录行错位。 */
.ledger-head { display: flex; align-items: center; border-bottom: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 12px; }
.ledger-head .head-cell { padding: var(--space-2) var(--space-4); }
.ledger-head .head-cell:first-child { flex: 0 0 190px; }
.ledger-head .head-cell:nth-child(2) { flex: 1 1 auto; }
.head-cache { display: flex; flex: 0 0 auto; flex-direction: column; align-items: flex-end; gap: 2px; margin: 0; padding: var(--space-2) var(--space-4); color: var(--color-text-secondary); text-align: right; }
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
.kind-tag[data-kind="session"] { background: var(--color-event-session); }
.kind-tag[data-kind="user"] { background: var(--color-event-user); }
.kind-tag[data-kind="context"] { background: var(--color-event-context); }
.kind-tag[data-kind="model_request"] { background: var(--color-event-model-request); }
.kind-tag[data-kind="model_response"] { background: var(--color-event-model-response); }
.kind-tag[data-kind="model_error"] { background: var(--color-event-model-error); }
.kind-tag[data-kind="state_change"] { background: var(--color-event-state-change); }
.record-summary { flex: 1 1 auto; min-width: 0; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* 展开区跨满两列；正文按原文换行，超出视口高度时在区内滚动，不淹没整页。 */
.record-full-block { grid-column: 1 / -1; border-top: 1px dashed var(--color-border); }
.record-full-bar { display: flex; align-items: center; justify-content: flex-end; gap: var(--space-3); padding: var(--space-2) var(--space-4) 0; }
.record-full-size { margin-right: auto; color: var(--color-text-muted); font-size: 12px; }
.copy-button { padding: 1px var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-sm); color: var(--color-text-secondary); background: var(--color-surface); cursor: pointer; font: inherit; font-size: 12px; }
.copy-button:hover { border-color: var(--color-brand-700); color: var(--color-brand-700); }
.copy-error { color: var(--color-error-700); font-size: 12px; }
.record-full { max-height: 60vh; overflow: auto; margin: 0; padding: var(--space-2) var(--space-4) var(--space-4); color: var(--color-text-primary); background: var(--color-surface); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
.record-duration, .record-time { flex: 0 0 auto; color: var(--color-text-muted); font-size: var(--font-size-sm); }
.record-time { min-width: 68px; text-align: right; }
.record-status { flex: 0 0 auto; padding: 1px var(--space-2); border-radius: var(--radius-sm); font-size: 12px; }
.record-status.failed { color: var(--color-error-700); background: var(--color-error-100); }
.record-status.pending { color: var(--color-text-secondary); background: var(--color-surface-muted); }
/* margin-left:auto 把按钮钉在内容列右端：展开后摘要（flex:1）被移除，否则按钮会左跳到时间戳旁。 */
.expand-button { flex: 0 0 auto; margin-left: auto; padding: 1px var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-sm); color: var(--color-text-secondary); background: var(--color-surface); cursor: pointer; font: inherit; font-size: 12px; }
.expand-button:hover { border-color: var(--color-brand-700); color: var(--color-brand-700); }
.group-row { cursor: pointer; background: var(--color-surface-muted); }
.group-row:focus-visible { outline: 2px solid var(--color-brand-600); outline-offset: -2px; }
.group-row > * { display: inline-flex; align-items: center; padding: var(--space-2) 0; }
.group-ellipsis { padding-left: var(--space-4); color: var(--color-text-muted); }
.group-text { color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.group-summary { min-width: 0; overflow: hidden; color: var(--color-text-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.empty-state { margin: 0; padding: var(--space-4); color: var(--color-text-muted); }
@media (max-width: 640px) {
  .record-row, .group-row { grid-template-columns: 128px minmax(0, 1fr); }
  .ledger-head { flex-wrap: wrap; }
  .ledger-head .head-cell:first-child { flex-basis: 128px; }
  .head-cache { flex-basis: 100%; align-items: flex-start; padding-top: 0; text-align: left; }
  .event-cell, .content-cell { padding: var(--space-2) var(--space-3); }
  .record-time { display: none; }
}
</style>
