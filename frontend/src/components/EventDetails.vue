<script setup lang="ts">
import { computed, ref, watch } from "vue"

import JsonTree from "./JsonTree.vue"
import { fetchSessionSurface } from "../api/session-events"
import { formatDateTime, formatDuration } from "../utils/trajectoryTime"
import type { Surface, TrajectoryRecord } from "../types/session-event"

type DetailTab =
  | "overview"
  | "content"
  | "messages"
  | "output"
  | "surface"
  | "raw"

interface TabItem {
  id: DetailTab
  label: string
}

const props = defineProps<{
  record: TrajectoryRecord
  sessionId: string
  records: TrajectoryRecord[]
}>()

const emit = defineEmits<{
  close: []
  select: [seq: number]
}>()

const activeTab = ref<DetailTab>("overview")
const surface = ref<Surface>()
const surfaceError = ref("")
const surfaceLoading = ref(false)

watch(
  () => props.record.eventSeq,
  () => {
    activeTab.value = "overview"
    surface.value = undefined
    surfaceError.value = ""
  },
)

const tabs = computed<TabItem[]>(() => {
  const items: TabItem[] = [{ id: "overview", label: "概述" }]
  const detail = props.record.detail
  if (detail.user !== undefined || detail.context !== undefined) {
    items.push({ id: "content", label: "内容" })
  }
  const request = detail.modelRequest
  if (request !== undefined) {
    items.push({ id: "messages", label: `消息（${request.messages.length}）` })
    items.push({ id: "surface", label: "模型上下文" })
  }
  if (detail.modelResponse !== undefined || detail.modelError !== undefined) {
    items.push({ id: "output", label: "输出" })
  }
  items.push({ id: "raw", label: "原始 JSON" })
  return items
})

const statusLabel = computed(() => {
  if (props.record.status === "failed") return "失败"
  if (props.record.status === "pending") return "等待中"
  return "已完成"
})

const parentRecord = computed<TrajectoryRecord | undefined>(() =>
  props.records.find((candidate) => candidate.eventId === props.record.parentEventId),
)

const childRecords = computed<TrajectoryRecord[]>(() =>
  props.records.filter((candidate) => candidate.parentEventId === props.record.eventId),
)

function displayTime(value: string): string {
  return formatDateTime(value)
}

function messageRole(message: Record<string, unknown>): string {
  const role = message.role
  return typeof role === "string" ? role : "unknown"
}

function messageContent(message: Record<string, unknown>): string {
  const content = message.content
  return typeof content === "string" ? content : JSON.stringify(content, null, 2)
}

async function loadSurface() {
  const request = props.record.detail.modelRequest
  if (request === undefined) return
  surfaceLoading.value = true
  surfaceError.value = ""
  try {
    surface.value = await fetchSessionSurface(props.sessionId, request.surfaceSeq)
  } catch (error) {
    surfaceError.value = error instanceof Error ? error.message : String(error)
  } finally {
    surfaceLoading.value = false
  }
}

function activateTab(id: DetailTab) {
  activeTab.value = id
  if (id === "surface" && surface.value === undefined && surfaceError.value === "") {
    void loadSurface()
  }
}
</script>

<template>
  <aside class="details" aria-label="事件详情">
    <header class="details-header">
      <div class="details-title">
        <span class="kind-tag" :data-kind="record.kind">{{ record.label }}</span>
        <strong>#{{ record.eventSeq }}</strong>
      </div>
      <button type="button" class="details-close" aria-label="关闭详情" @click="emit('close')">关闭</button>
    </header>

    <div class="detail-tabs" role="tablist" aria-label="事件详情">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        role="tab"
        :aria-selected="activeTab === tab.id"
        :class="['detail-tab', { active: activeTab === tab.id }]"
        @click="activateTab(tab.id)"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="detail-body" role="tabpanel">
      <template v-if="activeTab === 'overview'">
        <dl class="overview">
          <div>
            <dt>状态</dt>
            <dd :class="{ 'status-failed': record.status === 'failed' }">{{ statusLabel }}</dd>
          </div>
          <div>
            <dt>事件类型</dt>
            <dd class="mono">{{ record.eventType }}</dd>
          </div>
          <div>
            <dt>发生时间</dt>
            <dd>{{ displayTime(record.occurredAt) }}</dd>
          </div>
          <div>
            <dt>耗时</dt>
            <dd>{{ formatDuration(record.durationMs) }}</dd>
          </div>
          <div v-if="parentRecord">
            <dt>父事件</dt>
            <dd>
              <button type="button" class="link" @click="emit('select', parentRecord.eventSeq)">
                #{{ parentRecord.eventSeq }} {{ parentRecord.label }}
              </button>
            </dd>
          </div>
          <div v-if="childRecords.length">
            <dt>直接结果</dt>
            <dd class="link-list">
              <button
                v-for="child in childRecords"
                :key="child.eventSeq"
                type="button"
                class="link"
                @click="emit('select', child.eventSeq)"
              >
                #{{ child.eventSeq }} {{ child.label }}
              </button>
            </dd>
          </div>
        </dl>
      </template>

      <template v-else-if="activeTab === 'content'">
        <section v-if="record.detail.user" class="detail-section">
          <h3>学生输入</h3>
          <p class="detail-note">输入方式：{{ record.detail.user.inputType === "voice" ? "语音" : "文本" }}</p>
          <pre class="plain-text">{{ record.detail.user.text }}</pre>
        </section>
        <section v-if="record.detail.context" class="detail-section">
          <h3>上下文</h3>
          <p class="detail-note">{{ record.detail.context.kind }} · {{ record.detail.context.source }}</p>
          <JsonTree :value="record.detail.context.content" />
        </section>
      </template>

      <template v-else-if="activeTab === 'messages' && record.detail.modelRequest">
        <p class="detail-note">
          {{ record.detail.modelRequest.provider }} / {{ record.detail.modelRequest.model }} ·
          {{ record.detail.modelRequest.messages.length }} 条消息
        </p>
        <ol class="message-list">
          <li v-for="(message, index) in record.detail.modelRequest.messages" :key="index" class="message-item">
            <header>
              <span class="message-role">{{ messageRole(message) }}</span>
              <span class="message-index">#{{ index + 1 }}</span>
            </header>
            <pre class="plain-text">{{ messageContent(message) }}</pre>
          </li>
        </ol>
      </template>

      <template v-else-if="activeTab === 'surface'">
        <p v-if="surfaceLoading" class="detail-note">正在读取模型上下文……</p>
        <p v-else-if="surfaceError" class="detail-error">{{ surfaceError }}</p>
        <template v-else-if="surface">
          <p class="detail-note">
            按 surfaceSeq #{{ surface.asOfSeq }} 重建：该请求发出前模型可见的学生消息与上下文。
          </p>
          <section class="detail-section">
            <h3>学生消息（{{ surface.messages.length }}）</h3>
            <p v-if="surface.messages.length === 0" class="detail-note">该时点没有学生消息。</p>
            <article v-for="message in surface.messages" :key="message.seq" class="surface-message">
              <header><strong>{{ message.role }}</strong><span>#{{ message.seq }}</span></header>
              <pre class="plain-text">{{ message.content }}</pre>
            </article>
          </section>
          <section class="detail-section">
            <h3>上下文（{{ surface.contexts.length }}）</h3>
            <p v-if="surface.contexts.length === 0" class="detail-note">该时点没有附加上下文。</p>
            <details v-for="context in surface.contexts" :key="context.seq" class="surface-context" open>
              <summary><span>{{ context.kind }}</span><small>#{{ context.seq }} · {{ context.source }}</small></summary>
              <JsonTree :value="context.content" />
            </details>
          </section>
        </template>
      </template>

      <template v-else-if="activeTab === 'output'">
        <section v-if="record.detail.modelResponse" class="detail-section">
          <p class="detail-note">
            校验：{{ record.detail.modelResponse.validation }} ·
            输入 {{ record.detail.modelResponse.inputTokens ?? "未记录" }} tok ·
            输出 {{ record.detail.modelResponse.outputTokens ?? "未记录" }} tok
          </p>
          <p v-if="record.detail.modelResponse.promptCacheHitTokens !== undefined || record.detail.modelResponse.promptCacheMissTokens !== undefined" class="detail-note">
            缓存命中 {{ record.detail.modelResponse.promptCacheHitTokens ?? 0 }} tok ·
            缓存未命中 {{ record.detail.modelResponse.promptCacheMissTokens ?? 0 }} tok
          </p>
          <h3>判词输出</h3>
          <JsonTree :value="record.detail.modelResponse.output" />
          <h3>模型原始回复</h3>
          <pre v-if="record.detail.modelResponse.rawContent" class="plain-text">{{ record.detail.modelResponse.rawContent }}</pre>
          <p v-else class="detail-note">该历史事件未保存模型原始回复。</p>
        </section>
        <section v-if="record.detail.modelError" class="detail-section">
          <p class="detail-error">
            {{ record.detail.modelError.errorType }}：{{ record.detail.modelError.message }}
          </p>
        </section>
      </template>

      <template v-else>
        <JsonTree :value="record" />
      </template>
    </div>
  </aside>
</template>

<style scoped>
.details { display: flex; flex-direction: column; min-width: 0; overflow: hidden; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.details-header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--color-border); }
.details-title { display: flex; align-items: center; gap: var(--space-2); }
.details-close { padding: 0; border: none; color: var(--color-brand-700); background: none; cursor: pointer; font: inherit; font-size: var(--font-size-sm); }
.kind-tag { padding: 2px var(--space-2); border-radius: 999px; color: #ffffff; background: #64748b; font-size: 12px; white-space: nowrap; }
.kind-tag[data-kind="session"] { background: #94a3b8; }
.kind-tag[data-kind="user"] { background: var(--color-brand-700); }
.kind-tag[data-kind="context"] { background: #0ea5e9; }
.kind-tag[data-kind="model_request"] { background: #7c3aed; }
.kind-tag[data-kind="model_response"] { background: #16a34a; }
.kind-tag[data-kind="model_error"] { background: #dc2626; }
.kind-tag[data-kind="state_change"] { background: #d97706; }
.detail-tabs { display: flex; flex-wrap: wrap; gap: var(--space-1); padding: var(--space-2) var(--space-4); border-bottom: 1px solid var(--color-border); }
.detail-tab { padding: var(--space-1) var(--space-3); border: 1px solid transparent; border-radius: var(--radius-sm); color: var(--color-text-secondary); background: none; cursor: pointer; font: inherit; font-size: var(--font-size-sm); }
.detail-tab.active { border-color: var(--color-brand-700); color: var(--color-on-brand); background: var(--color-brand-700); }
.detail-body { flex: 1 1 auto; min-height: 0; padding: var(--space-4); overflow: auto; }
.overview { display: grid; gap: var(--space-3); margin: 0; }
.overview > div { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: var(--space-3); align-items: baseline; }
.overview dt { color: var(--color-text-muted); font-size: var(--font-size-sm); }
.overview dd { margin: 0; overflow-wrap: anywhere; }
.overview dd.status-failed { color: var(--color-error-700); }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
.link, .link-list .link { padding: 0; border: none; color: var(--color-brand-700); background: none; cursor: pointer; font: inherit; }
.link-list { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.detail-section + .detail-section { margin-top: var(--space-4); }
.detail-section h3 { margin: var(--space-3) 0 var(--space-2); font-size: var(--font-size-base); }
.detail-section h3:first-child { margin-top: 0; }
.detail-note { margin: 0 0 var(--space-2); color: var(--color-text-muted); font-size: var(--font-size-sm); }
.detail-error { margin: 0 0 var(--space-2); padding: var(--space-2); border-radius: var(--radius-sm); color: var(--color-error-700); background: var(--color-error-100); overflow-wrap: anywhere; }
.plain-text { max-height: 320px; overflow: auto; margin: 0; padding: var(--space-3); border-radius: var(--radius-sm); background: var(--color-surface-muted); font-size: 13px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
.message-list { display: grid; gap: var(--space-3); margin: 0; padding: 0; list-style: none; }
.message-item header { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-1); }
.message-role { color: var(--color-brand-700); font-size: var(--font-size-sm); font-weight: 600; }
.message-index { color: var(--color-text-muted); font-size: 12px; }
.surface-message { margin-top: var(--space-2); padding: var(--space-3); border-left: 3px solid var(--color-brand-600); border-radius: var(--radius-sm); background: var(--color-brand-50); }
.surface-message header { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-2); }
.surface-message header span { color: var(--color-text-muted); font-size: 12px; }
.surface-context { margin-top: var(--space-3); padding-top: var(--space-3); border-top: 1px solid var(--color-border); }
.surface-context summary { display: flex; justify-content: space-between; gap: var(--space-3); cursor: pointer; color: var(--color-brand-700); }
.surface-context summary small { color: var(--color-text-muted); font-size: 12px; }
</style>
