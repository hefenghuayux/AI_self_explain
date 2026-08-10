<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { useRoute } from "vue-router"

import { exportSessionTrace, fetchSessionTrace } from "../api/audit"
import type { AuditExport, SessionTrace, TraceEvent } from "../types/audit"

type ViewMode = "BUSINESS" | "AUDIT"

interface TraceGroup {
  key: string
  title: string
  description: string
  events: TraceEvent[]
  relatedEvents: TraceEvent[]
}

interface RequestGroup {
  key: string
  label: string
  events: TraceEvent[]
}

const route = useRoute()
const sessionId = String(route.params.sessionId)
const trace = ref<SessionTrace>()
const loading = ref(true)
const exporting = ref(false)
const errorMessage = ref("")
const exportResult = ref<AuditExport>()
const viewMode = ref<ViewMode>("BUSINESS")
const selectedEventName = ref("ALL")

const eventNames = computed(() => [
  "ALL",
  ...new Set(trace.value?.events.map((event) => event.eventName) ?? []),
])

const filteredEvents = computed<TraceEvent[]>(() => {
  if (!trace.value || selectedEventName.value === "ALL") return trace.value?.events ?? []
  return trace.value.events.filter((event) => event.eventName === selectedEventName.value)
})

function operationName(event: TraceEvent): string {
  return typeof event.operation.name === "string" ? event.operation.name : ""
}

function eventTitle(event: TraceEvent): string {
  const operation = operationName(event)
  return event.eventName === "state.transitioned" && operation
    ? `${event.eventName} · ${operation}`
    : event.eventName
}

function eventTime(occurredAt: string): string {
  return new Date(occurredAt).toLocaleString("zh-CN", { hour12: false })
}

function groupEventCount(group: TraceGroup): number {
  return group.events.length + group.relatedEvents.length
}

function groupStatus(group: TraceGroup): string {
  return [...group.events, ...group.relatedEvents].some((event) => event.result.status === "ERROR")
    ? "ERROR"
    : "SUCCESS"
}

const businessGroups = computed<TraceGroup[]>(() => {
  const groups: TraceGroup[] = [
    {
      key: "session-start",
      title: "会话开始并选择输入方式",
      description: "记录会话建立和输入方式选择。",
      events: [],
      relatedEvents: [],
    },
    {
      key: "student-submission",
      title: "学生提交答案",
      description: "记录学生输入确认、正式提交以及语音输入相关过程。",
      events: [],
      relatedEvents: [],
    },
    {
      key: "ai-evaluation",
      title: "AI 调用并完成结构化评价",
      description: "将模型调用技术记录和结构化评价结果放在同一业务阶段下。",
      events: [],
      relatedEvents: [],
    },
    {
      key: "rule-application",
      title: "后端应用确定性规则",
      description: "记录后端根据评价结果执行的状态、计数和阈值规则。",
      events: [],
      relatedEvents: [],
    },
    {
      key: "support-generation",
      title: "生成并保存教学反馈",
      description: "记录最终保存并提供给学生的反馈、提示或引导问题。",
      events: [],
      relatedEvents: [],
    },
    {
      key: "other",
      title: "其他审计事件",
      description: "保留当前业务阶段未覆盖的事件，避免新增事件被默认视图隐藏。",
      events: [],
      relatedEvents: [],
    },
  ]

  for (const event of trace.value?.events ?? []) {
    const operation = operationName(event)
    if (event.eventName === "session.created" || operation === "SELECT_INITIAL_CHOICE") {
      groups[0].events.push(event)
    } else if (
      event.eventName === "student.explanation.submitted" ||
      event.eventName === "student.input.submitted"
    ) {
      groups[1].events.push(event)
    } else if (
      [
        "voice.transcription.completed",
        "audio.persisted",
      ].includes(event.eventName) ||
      event.eventName.startsWith("asr.call.") ||
      operation.startsWith("SUBMIT_")
    ) {
      groups[1].relatedEvents.push(event)
    } else if (event.eventName.startsWith("ai.output.")) {
      groups[2].events.push(event)
    } else if (event.eventName.startsWith("ai.call.")) {
      groups[2].relatedEvents.push(event)
    } else if (event.eventName === "support.generated") {
      groups[4].events.push(event)
    } else if (event.eventName === "state.transitioned") {
      groups[3].events.push(event)
    } else {
      groups[5].events.push(event)
    }
  }

  return groups.filter((group) => groupEventCount(group) > 0)
})

const requestGroups = computed<RequestGroup[]>(() => {
  const groupedEvents = new Map<string, TraceEvent[]>()
  for (const event of filteredEvents.value) {
    const requestId = event.correlation.requestId ?? "NO_REQUEST_ID"
    const events = groupedEvents.get(requestId) ?? []
    events.push(event)
    groupedEvents.set(requestId, events)
  }
  return Array.from(groupedEvents, ([key, events]) => ({
    key,
    label: key === "NO_REQUEST_ID" ? "无 requestId（会话级事件）" : `requestId · ${key}`,
    events,
  }))
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
          <div class="view-switch" role="tablist" aria-label="审计视图">
            <button
              type="button"
              :class="{ active: viewMode === 'BUSINESS' }"
              :aria-pressed="viewMode === 'BUSINESS'"
              @click="viewMode = 'BUSINESS'"
            >
              业务链路
            </button>
            <button
              type="button"
              :class="{ active: viewMode === 'AUDIT' }"
              :aria-pressed="viewMode === 'AUDIT'"
              @click="viewMode = 'AUDIT'"
            >
              完整审计
            </button>
          </div>
        </div>
        <template v-if="viewMode === 'BUSINESS'">
          <p class="view-description">默认按业务阶段阅读，技术调用和状态细节仍保留在阶段内。</p>
          <p v-if="!businessGroups.length" class="empty-state">没有可展示的业务事件。</p>
          <details v-for="group in businessGroups" :key="group.key" class="trace-group" open>
            <summary>
              <span class="group-title">{{ group.title }}</span>
              <span>{{ groupEventCount(group) }} 个事件 · {{ groupStatus(group) }}</span>
            </summary>
            <p class="group-description">{{ group.description }}</p>
            <details v-for="event in group.events" :key="event.eventId" class="event-card">
              <summary>
                <span>#{{ event.sequence }} {{ eventTitle(event) }}</span>
                <span>{{ event.result.status }} · {{ eventTime(event.occurredAt) }}</span>
              </summary>
              <div class="event-meta">
                <span v-if="event.correlation.requestId">requestId: {{ event.correlation.requestId }}</span>
                <span v-if="typeof event.result.durationMs === 'number'">耗时: {{ event.result.durationMs }} ms</span>
              </div>
              <pre>{{ eventJson(event) }}</pre>
            </details>
            <details v-if="group.relatedEvents.length" class="related-events">
              <summary>相关技术事件 · {{ group.relatedEvents.length }} 项</summary>
              <details v-for="event in group.relatedEvents" :key="event.eventId" class="event-card">
                <summary>
                  <span>#{{ event.sequence }} {{ eventTitle(event) }}</span>
                  <span>{{ event.result.status }} · {{ eventTime(event.occurredAt) }}</span>
                </summary>
                <div class="event-meta">
                  <span v-if="event.correlation.requestId">requestId: {{ event.correlation.requestId }}</span>
                  <span v-if="typeof event.result.durationMs === 'number'">耗时: {{ event.result.durationMs }} ms</span>
                </div>
                <pre>{{ eventJson(event) }}</pre>
              </details>
            </details>
          </details>
        </template>
        <template v-else>
          <div class="audit-filter">
            <p class="view-description">按 requestId 分组查看完整审计事件；展开单条事件可查看原始 JSON。</p>
            <label>
              事件类型
              <select v-model="selectedEventName">
                <option v-for="eventName in eventNames" :key="eventName" :value="eventName">
                  {{ eventName === "ALL" ? "全部" : eventName }}
                </option>
              </select>
            </label>
          </div>
          <p v-if="!filteredEvents.length" class="empty-state">没有符合条件的事件。</p>
          <details v-for="group in requestGroups" :key="group.key" class="trace-group" open>
            <summary>
              <span class="group-title">{{ group.label }}</span>
              <span>{{ group.events.length }} 个事件</span>
            </summary>
            <details v-for="event in group.events" :key="event.eventId" class="event-card">
              <summary>
                <span>#{{ event.sequence }} {{ eventTitle(event) }}</span>
                <span>{{ event.result.status }} · {{ eventTime(event.occurredAt) }}</span>
              </summary>
              <div class="event-meta">
                <span v-if="typeof event.result.durationMs === 'number'">耗时: {{ event.result.durationMs }} ms</span>
              </div>
              <pre>{{ eventJson(event) }}</pre>
            </details>
          </details>
        </template>
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
.view-switch { display: flex; gap: 8px; }
.view-switch button { padding: 7px 12px; color: #1d4ed8; background: #eff6ff; }
.view-switch button.active { color: #fff; background: #2563eb; }
.view-description { margin: 0 0 16px; color: #6b7280; }
.audit-filter { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
select { margin-left: 8px; padding: 6px 8px; }
.trace-group { border-top: 1px solid #e5e7eb; padding: 12px 0; }
.trace-group > summary { display: flex; justify-content: space-between; gap: 12px; cursor: pointer; }
.trace-group > summary > span:first-child { min-width: 0; overflow-wrap: anywhere; }
.trace-group > summary > span:last-child { color: #6b7280; font-size: 13px; text-align: right; }
.group-title { font-weight: 600; }
.group-description { margin: 10px 0 0; color: #6b7280; font-size: 13px; }
.related-events { margin: 12px 0 0 12px; padding: 10px 12px; border-radius: 6px; background: #f8fafc; }
.related-events > summary { cursor: pointer; color: #475569; font-size: 13px; }
.event-card { border-top: 1px solid #e5e7eb; padding: 12px 0; }
.trace-group > .event-card { margin-top: 12px; padding-left: 12px; }
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
  .audit-filter { align-items: flex-start; flex-direction: column; }
  .trace-group > summary { align-items: flex-start; flex-direction: column; }
  .trace-group > summary > span:last-child { text-align: left; }
  .event-card summary { align-items: flex-start; flex-direction: column; }
  .event-card summary span:last-child { text-align: left; }
}
</style>
