<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { useRoute } from "vue-router"

import { exportSessionTrace, fetchSessionTrace } from "../api/audit"
import type { AuditExport, SessionTrace, TraceEvent } from "../types/audit"

interface ReadableField {
  path: string
  label: string
  value: string
  description: string
}

const route = useRoute()
const sessionId = String(route.params.sessionId)
const trace = ref<SessionTrace>()
const loading = ref(true)
const exporting = ref(false)
const errorMessage = ref("")
const exportResult = ref<AuditExport>()
const selectedEventName = ref("ALL")

const eventLabels: Record<string, string> = {
  "session.created": "会话已创建",
  "state.transitioned": "业务状态已转换",
  "student.input.submitted": "学生输入已提交",
  "student.input.confirmed": "学生输入已确认",
  "voice.capture.completed": "语音采集已完成",
  "asr.call.completed": "语音识别已完成",
  "asr.call.failed": "语音识别失败",
  "ai.call.completed": "AI 调用已完成",
  "ai.call.failed": "AI 调用失败",
  "ai.output.validated": "AI 评价校验通过",
  "ai.output.validation_failed": "AI 评价校验失败",
  "support.generated": "教学支持已生成",
  "audio.persisted": "音频文件已保存",
}

const fieldDescriptions: Record<string, { label: string; description: string }> = {
  schemaVersion: { label: "结构版本", description: "说明这条日志遵循哪一版日志数据契约。" },
  eventId: { label: "事件编号", description: "这条事件的唯一编号，用于去重和定位原始记录。" },
  sequence: { label: "链路顺序", description: "这条事件在当前会话审计链路中的先后顺序。" },
  occurredAt: { label: "发生时间", description: "业务事件实际发生的时间。" },
  eventName: { label: "事件类型", description: "说明系统执行了哪一类动作。" },
  severity: { label: "严重级别", description: "说明这是普通信息、警告还是错误。" },
  "source.service": { label: "来源服务", description: "产生这条事件的应用服务。" },
  "source.module": { label: "来源模块", description: "产生这条事件的后端功能模块。" },
  "correlation.sessionId": { label: "会话编号", description: "贯穿整个学习会话的业务编号。" },
  "correlation.requestId": { label: "请求编号", description: "一次 HTTP 或 WebSocket 请求的编号。" },
  "correlation.traceId": { label: "交互链路编号", description: "把一次用户交互中的多个步骤串起来。" },
  "correlation.spanId": { label: "当前步骤编号", description: "当前内部步骤的编号，例如一次 AI 调用。" },
  "correlation.parentSpanId": { label: "父步骤编号", description: "当前步骤所属的上级步骤；为空表示没有父步骤。" },
  "operation.name": { label: "操作名称", description: "业务代码对当前操作使用的名称。" },
  "operation.kind": { label: "操作类别", description: "区分状态转换、学生输入、AI 调用等操作类型。" },
  "operation.attemptNumber": { label: "尝试次数", description: "外部服务第几次调用，包含重试次数。" },
  "result.status": { label: "执行结果", description: "说明当前步骤成功、失败或处于其他结果状态。" },
  "result.durationMs": { label: "耗时", description: "当前步骤耗时，单位是毫秒。" },
  "result.errorType": { label: "错误类型", description: "后端定义的错误分类，例如 AI_SCHEMA_ERROR。" },
  "result.errorMessage": { label: "错误信息", description: "失败时记录的具体错误原因。" },
  "data.fromStatus": { label: "原业务状态", description: "状态转换前的会话状态。" },
  "data.toStatus": { label: "新业务状态", description: "状态转换后的会话状态。" },
  "data.fromFlowStage": { label: "原流程阶段", description: "流程阶段转换前的位置。" },
  "data.toFlowStage": { label: "新流程阶段", description: "流程阶段转换后的位置。" },
  "data.beforeSnapshot": { label: "转换前快照", description: "状态转换前的状态、轮次和计数信息。" },
  "data.afterSnapshot": { label: "转换后快照", description: "状态转换后的状态、轮次和计数信息。" },
  "data.round": { label: "教学轮次", description: "本条事件发生时所在的自讲轮次。" },
  "data.provider": { label: "服务提供商", description: "实际被调用的 AI 或 ASR 服务提供商。" },
  "data.model": { label: "模型名称", description: "实际被调用的模型。" },
  "data.promptVersion": { label: "提示词版本", description: "生成 AI 请求时使用的提示词版本。" },
  "data.validationStatus": { label: "校验状态", description: "AI 返回结构是否通过后端 Schema 和关系校验。" },
  "data.correctness": { label: "正确性判断", description: "AI 对学生答案正确性的结构化判断。" },
  "data.completeness": { label: "完整性判断", description: "AI 对学生答案完整性的结构化判断。" },
  "data.coveredPoints": { label: "已覆盖评分点", description: "AI 判断学生已经覆盖的题目评分点。" },
  "data.missingPoints": { label: "未覆盖评分点", description: "AI 判断学生仍然缺少的题目评分点。" },
  "data.nextAction": { label: "下一步动作", description: "确定性规则将根据 AI 评价决定的下一步教学动作。" },
  "data.content": { label: "展示内容摘要", description: "展示给学生的内容；原始敏感输入不会直接写入这里。" },
  "data.confirmedText": { label: "确认文本摘要", description: "学生确认文本的长度和摘要，不直接展示原文。" },
  "data.asrTranscript": { label: "语音转写摘要", description: "ASR 转写文本的长度和摘要，不直接展示原文。" },
  "data.rawResponse": { label: "原始响应摘要", description: "外部服务原始响应的长度和 SHA-256，不直接展示完整响应。" },
  "data.characterCount": { label: "字符数量", description: "对应原始文本的字符数。" },
  "data.sha256": { label: "内容摘要", description: "内容的 SHA-256，用于确认内容是否发生变化。" },
  "references.stateTransitionEventId": { label: "状态事件编号", description: "对应数据库 state_transition_events 表的记录。" },
  "references.externalCallRecordId": { label: "外部调用编号", description: "对应数据库 external_call_records 表的记录。" },
  "references.attemptId": { label: "自讲尝试编号", description: "对应学生本次自讲尝试的数据库记录。" },
  "references.evaluationId": { label: "评价编号", description: "对应 AI 评价记录的数据库编号。" },
  "references.supportEventId": { label: "支持事件编号", description: "对应教学支持记录的数据库编号。" },
  "references.audioFileId": { label: "音频文件编号", description: "对应音频元数据记录的数据库编号。" },
  "privacy.redactedFields": { label: "已脱敏字段", description: "列出为了隐私安全没有直接展示的字段。" },
}

const valueLabels: Record<string, string> = {
  ALL: "全部事件",
  SUCCESS: "成功",
  ERROR: "失败",
  WARNING: "警告",
  INFO: "信息",
  IN_PROGRESS: "进行中",
  PAUSED: "已暂停",
  COMPLETED: "已完成",
  NEED_HUMAN: "需要人工处理",
  WAIT_INITIAL_CHOICE: "等待初始选择",
  CAPTURING_INPUT: "采集中",
  TRANSCRIBING: "语音转写中",
  AI_EVALUATING: "AI 评价中",
  WAIT_STUDENT_ACTION: "等待学生操作",
  WAIT_GUIDED_ANSWERS: "等待回答引导问题",
  SHOWING_FULL_SOLUTION: "展示完整解析",
}

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

function eventLabel(eventName: string): string {
  return eventLabels[eventName] ?? eventName
}

function valueLabel(value: unknown): string {
  if (typeof value !== "string") return displayValue(value)
  return valueLabels[value] ?? value
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未提供"
  if (typeof value === "object") return JSON.stringify(value, null, 2)
  return String(value)
}

function fieldInfo(path: string): { label: string; description: string } {
  return fieldDescriptions[path] ?? {
    label: path.split(".")[path.split(".").length - 1] ?? path,
    description: "该字段是当前事件携带的业务数据，具体含义取决于事件类型。",
  }
}

function readableFields(event: TraceEvent): ReadableField[] {
  const fields: ReadableField[] = []

  function append(value: unknown, path: string) {
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      const entries = Object.entries(value as Record<string, unknown>)
      if (!entries.length) {
        const info = fieldInfo(path)
        fields.push({ path, label: info.label, value: "空对象", description: info.description })
        return
      }
      for (const [key, childValue] of entries) {
        append(childValue, path ? `${path}.${key}` : key)
      }
      return
    }

    const info = fieldInfo(path)
    fields.push({
      path,
      label: info.label,
      value: displayValue(value),
      description: info.description,
    })
  }

  append(event, "")
  return fields
}

function readableEventSummary(event: TraceEvent): string {
  if (event.eventName === "state.transitioned") {
    const fromStage = valueLabel(event.data.fromFlowStage)
    const toStage = valueLabel(event.data.toFlowStage)
    return `流程从“${fromStage}”转换为“${toStage}”，这是由后端确定性规则记录的状态变化。`
  }
  if (event.eventName === "ai.call.completed") {
    return `AI 已完成一次模型调用，${event.data.model ?? "未提供模型"}耗时 ${event.result.durationMs ?? "未知"} 毫秒。`
  }
  if (event.eventName === "asr.call.completed") {
    return `语音识别服务已返回结果，耗时 ${event.result.durationMs ?? "未知"} 毫秒。`
  }
  if (event.eventName === "ai.output.validation_failed") {
    return "AI 返回结果未通过后端结构校验，系统不会直接把它当作合法教学评价。"
  }
  if (event.eventName === "student.input.submitted") {
    return "学生输入已保存，并进入后续评价或教学支持流程。"
  }
  if (event.eventName === "support.generated") {
    return "系统已生成一条教学支持记录，具体支持类型见下方字段解释。"
  }
  return `${eventLabel(event.eventName)}，当前结果为“${valueLabel(event.result.status)}”。`
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
        <p class="eyebrow">AUDIT TRACE / 全链路审计</p>
        <h1>会话全链路审计</h1>
        <p>会话编号：{{ sessionId }}</p>
      </div>
      <div class="audit-actions">
        <RouterLink :to="`/sessions/${sessionId}`">返回会话</RouterLink>
        <button type="button" :disabled="exporting || loading" @click="exportTrace">
          {{ exporting ? "正在导出" : "生成 Markdown / JSONL" }}
        </button>
      </div>
    </header>

    <section class="reading-guide" aria-label="阅读说明">
      <strong>怎么读这页日志？</strong>
      <span>先看事件标题和执行摘要，再看“字段解释”；原始 JSON 只用于开发排查。</span>
    </section>

    <p v-if="errorMessage" class="error-state">{{ errorMessage }}</p>
    <p v-if="loading" class="loading-state">正在读取审计链路……</p>

    <template v-else-if="trace">
      <section class="summary-grid" aria-label="审计摘要">
        <article><span>会话状态</span><strong>{{ valueLabel(trace.summary.status) }}</strong></article>
        <article><span>流程阶段</span><strong>{{ valueLabel(trace.summary.flowStage) }}</strong></article>
        <article><span>事件数量</span><strong>{{ trace.summary.eventCount }}</strong></article>
        <article><span>外部调用</span><strong>{{ trace.summary.externalCallCount }}</strong></article>
        <article><span>错误数量</span><strong>{{ trace.summary.errorCount }}</strong></article>
      </section>

      <p v-if="exportResult" class="export-result">
        已导出 {{ exportResult.eventCount }} 个事件：{{ exportResult.markdownPath }}
      </p>

      <section class="event-section">
        <div class="section-header">
          <div>
            <h2>事件明细</h2>
            <p class="section-tip">每条事件都提供中文说明；英文名称只作为技术定位编号保留。</p>
          </div>
          <label>
            事件类型
            <select v-model="selectedEventName">
              <option v-for="eventName in eventNames" :key="eventName" :value="eventName">
                {{ eventName === "ALL" ? "全部事件" : eventLabel(eventName) }}
              </option>
            </select>
          </label>
        </div>
        <p v-if="!visibleEvents.length" class="empty-state">没有符合条件的事件。</p>
        <details v-for="event in visibleEvents" :key="event.eventId" class="event-card">
          <summary>
            <span class="event-title">#{{ event.sequence }} {{ eventLabel(event.eventName) }}</span>
            <span class="event-status">{{ valueLabel(event.result.status) }} · {{ new Date(event.occurredAt).toLocaleString("zh-CN", { hour12: false }) }}</span>
          </summary>
          <p class="event-technical-name">技术事件名：{{ event.eventName }}</p>
          <p class="event-summary">{{ readableEventSummary(event) }}</p>
          <div class="event-meta">
            <span>交互链路：{{ event.correlation.traceId }}</span>
            <span>当前步骤：{{ event.correlation.spanId }}</span>
            <span v-if="event.result.durationMs !== null">耗时：{{ event.result.durationMs }} 毫秒</span>
          </div>

          <section class="field-explanations">
            <h3>字段解释</h3>
            <div class="field-table" role="table" aria-label="日志字段解释">
              <div class="field-row field-header" role="row">
                <span>字段</span><span>当前值</span><span>这个字段表示什么</span>
              </div>
              <div v-for="field in readableFields(event)" :key="field.path" class="field-row" role="row">
                <div class="field-name"><strong>{{ field.label }}</strong><code>{{ field.path }}</code></div>
                <pre>{{ field.value }}</pre>
                <span>{{ field.description }}</span>
              </div>
            </div>
          </section>

          <details class="raw-json">
            <summary>查看原始 JSON（开发排查用）</summary>
            <pre>{{ eventJson(event) }}</pre>
          </details>
        </details>
      </section>
    </template>
  </main>
</template>

<style scoped>
.audit-page { max-width: 1180px; margin: 0 auto; padding: 24px; }
.audit-header, .section-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.audit-header { flex-wrap: wrap; }
.audit-header h1 { margin: 4px 0; }
.audit-header p { margin: 0; color: #6b7280; }
.eyebrow { color: #2563eb !important; font-size: 12px; letter-spacing: .12em; }
.audit-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.audit-actions a { color: #2563eb; }
button { border: 0; border-radius: 6px; padding: 9px 14px; color: #fff; background: #2563eb; cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .6; }
.reading-guide { display: flex; gap: 10px; flex-wrap: wrap; margin: 24px 0 12px; padding: 12px 14px; border-left: 4px solid #2563eb; background: #eff6ff; }
.reading-guide span, .section-tip { color: #4b5563; }
.summary-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin: 12px 0 24px; }
.summary-grid article { display: flex; min-height: 76px; flex-direction: column; justify-content: space-between; padding: 14px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; }
.summary-grid span { color: #6b7280; font-size: 13px; }
.summary-grid strong { font-size: 18px; overflow-wrap: anywhere; }
.event-section { padding: 20px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; }
.section-header { align-items: flex-start; margin-bottom: 16px; }
.section-header h2 { margin: 0; }
.section-tip { margin: 6px 0 0; font-size: 13px; }
select { margin-left: 8px; padding: 6px 8px; }
.event-card { border-top: 1px solid #e5e7eb; padding: 12px 0; }
.event-card summary { display: flex; justify-content: space-between; gap: 12px; cursor: pointer; list-style-position: inside; }
.event-title { font-weight: 700; }
.event-status { color: #6b7280; font-size: 13px; text-align: right; }
.event-technical-name { margin: 12px 0 0; color: #6b7280; font-family: Consolas, monospace; font-size: 12px; }
.event-summary { margin: 8px 0; line-height: 1.65; }
.event-meta { display: flex; gap: 12px; flex-wrap: wrap; margin: 12px 0; color: #6b7280; font-size: 13px; }
.field-explanations { margin-top: 16px; }
.field-explanations h3 { margin: 0 0 8px; font-size: 16px; }
.field-table { overflow: hidden; border: 1px solid #e5e7eb; border-radius: 6px; }
.field-row { display: grid; grid-template-columns: minmax(150px, 1fr) minmax(180px, 1.2fr) minmax(240px, 2fr); gap: 12px; padding: 10px 12px; border-top: 1px solid #e5e7eb; align-items: start; }
.field-row:first-child { border-top: 0; }
.field-header { color: #374151; background: #f9fafb; font-weight: 700; }
.field-name { display: flex; flex-direction: column; gap: 4px; }
.field-name strong { color: #111827; }
.field-name code { color: #1d4ed8; overflow-wrap: anywhere; }
.field-row pre { max-height: 160px; margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
pre { overflow: auto; padding: 10px; border-radius: 6px; background: #111827; color: #e5e7eb; font-family: Consolas, monospace; font-size: 12px; }
.raw-json { margin-top: 16px; }
.raw-json summary { color: #4b5563; cursor: pointer; font-size: 13px; }
.raw-json pre { max-height: 520px; margin: 10px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.error-state { padding: 12px; border-radius: 6px; color: #b91c1c; background: #fee2e2; }
.loading-state, .empty-state, .export-result { color: #6b7280; }
.export-result { overflow-wrap: anywhere; }
@media (max-width: 760px) {
  .audit-page { padding: 16px; }
  .summary-grid { grid-template-columns: repeat(2, 1fr); }
  .summary-grid article:last-child { grid-column: span 2; }
  .section-header { flex-direction: column; }
  .field-row { grid-template-columns: 1fr; gap: 6px; }
  .field-header { display: none; }
  .event-card summary { align-items: flex-start; flex-direction: column; }
  .event-status { text-align: left; }
}
</style>
