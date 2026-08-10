<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { useRoute } from "vue-router"

import { exportSessionTrace, fetchSessionTrace } from "../api/audit"
import type { AuditExport, SessionTrace, TraceEvent } from "../types/audit"

const route = useRoute()
const sessionId = String(route.params.sessionId)
const trace = ref<SessionTrace>()
const loading = ref(true)
const exporting = ref(false)
const errorMessage = ref("")
const exportResult = ref<AuditExport>()
const selectedEventName = ref("ALL")

const eventNames = computed(() => [
  "ALL",
  ...new Set(trace.value?.events.map((event) => event.eventName) ?? []),
])

const visibleEvents = computed<TraceEvent[]>(() => {
  if (!trace.value || selectedEventName.value === "ALL") return trace.value?.events ?? []
  return trace.value.events.filter((event) => event.eventName === selectedEventName.value)
})

async function loadTrace() {
  loading.value = true
  errorMessage.value = ""
  try {
    trace.value = await fetchSessionTrace(sessionId)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function exportTrace() {
  exporting.value = true
  errorMessage.value = ""
  try {
    exportResult.value = await exportSessionTrace(sessionId)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    exporting.value = false
  }
}

function eventJson(event: TraceEvent): string {
  return JSON.stringify(event, null, 2)
}

onMounted(loadTrace)
</script>

<template>
  <main class="audit-page">
    <header class="audit-header">
      <div>
        <p class="eyebrow">AUDIT TRACE</p>
        <h1>会话全链路审计</h1>
        <p>session-{{ sessionId }}</p>
      </div>
      <div class="audit-actions">
        <RouterLink :to="`/sessions/${sessionId}`">返回会话</RouterLink>
        <button type="button" :disabled="exporting || loading" @click="exportTrace">
          {{ exporting ? "正在导出" : "生成 Markdown / JSONL" }}
        </button>
      </div>
    </header>

    <p v-if="errorMessage" class="error-state">{{ errorMessage }}</p>
    <p v-if="loading" class="loading-state">正在读取审计链路……</p>

    <template v-else-if="trace">
      <section class="summary-grid" aria-label="审计摘要">
        <article><span>状态</span><strong>{{ trace.summary.status }}</strong></article>
        <article><span>流程阶段</span><strong>{{ trace.summary.flowStage }}</strong></article>
        <article><span>事件数量</span><strong>{{ trace.summary.eventCount }}</strong></article>
        <article><span>外部调用</span><strong>{{ trace.summary.externalCallCount }}</strong></article>
        <article><span>错误数量</span><strong>{{ trace.summary.errorCount }}</strong></article>
      </section>

      <p v-if="exportResult" class="export-result">
        已导出 {{ exportResult.eventCount }} 个事件：{{ exportResult.markdownPath }}
      </p>

      <section class="event-section">
        <div class="section-header">
          <h2>事件明细</h2>
          <label>
            事件类型
            <select v-model="selectedEventName">
              <option v-for="eventName in eventNames" :key="eventName" :value="eventName">
                {{ eventName === "ALL" ? "全部" : eventName }}
              </option>
            </select>
          </label>
        </div>
        <p v-if="!visibleEvents.length" class="empty-state">没有符合条件的事件。</p>
        <details v-for="event in visibleEvents" :key="event.eventId" class="event-card">
          <summary>
            <span>#{{ event.sequence }} {{ event.eventName }}</span>
            <span>{{ event.result.status }} · {{ new Date(event.occurredAt).toLocaleString("zh-CN", { hour12: false }) }}</span>
          </summary>
          <div class="event-meta">
            <span>Trace: {{ event.correlation.traceId }}</span>
            <span>Span: {{ event.correlation.spanId }}</span>
            <span v-if="event.result.durationMs !== null">耗时: {{ event.result.durationMs }} ms</span>
          </div>
          <pre>{{ eventJson(event) }}</pre>
        </details>
      </section>
    </template>
  </main>
</template>

<style scoped>
.audit-page { max-width: 1120px; margin: 0 auto; padding: 24px; }
.audit-header, .section-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.audit-header { flex-wrap: wrap; }
.audit-header h1 { margin: 4px 0; }
.audit-header p { margin: 0; color: #6b7280; }
.eyebrow { color: #2563eb !important; font-size: 12px; letter-spacing: .12em; }
.audit-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.audit-actions a { color: #2563eb; }
button { border: 0; border-radius: 6px; padding: 9px 14px; color: #fff; background: #2563eb; cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .6; }
.summary-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin: 24px 0; }
.summary-grid article { display: flex; min-height: 76px; flex-direction: column; justify-content: space-between; padding: 14px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; }
.summary-grid span { color: #6b7280; font-size: 13px; }
.summary-grid strong { font-size: 18px; overflow-wrap: anywhere; }
.event-section { padding: 20px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; }
.section-header { margin-bottom: 16px; }
.section-header h2 { margin: 0; }
select { margin-left: 8px; padding: 6px 8px; }
.event-card { border-top: 1px solid #e5e7eb; padding: 12px 0; }
.event-card summary { display: flex; justify-content: space-between; gap: 12px; cursor: pointer; list-style-position: inside; }
.event-card summary span:last-child { color: #6b7280; font-size: 13px; text-align: right; }
.event-meta { display: flex; gap: 12px; flex-wrap: wrap; margin: 12px 0; color: #6b7280; font-size: 13px; }
pre { max-height: 520px; overflow: auto; margin: 0; padding: 14px; border-radius: 6px; background: #111827; color: #e5e7eb; font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
.error-state { padding: 12px; border-radius: 6px; color: #b91c1c; background: #fee2e2; }
.loading-state, .empty-state, .export-result { color: #6b7280; }
.export-result { overflow-wrap: anywhere; }
@media (max-width: 760px) {
  .audit-page { padding: 16px; }
  .summary-grid { grid-template-columns: repeat(2, 1fr); }
  .summary-grid article:last-child { grid-column: span 2; }
  .section-header { align-items: flex-start; flex-direction: column; }
  .event-card summary { align-items: flex-start; flex-direction: column; }
  .event-card summary span:last-child { text-align: left; }
}
</style>
