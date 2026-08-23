<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import { useRoute } from "vue-router"

import {
  fetchSessionEvent,
  fetchSessionTrace,
  fetchSessionTrajectory,
} from "../api/session-events"
import type {
  SessionEvent,
  Trace,
  TraceNode,
  Trajectory,
  TrajectoryRun,
  TrajectoryStep,
} from "../types/session-event"

type ViewMode = "trajectory" | "trace"

const route = useRoute()
const sessionId = String(route.params.sessionId)
const viewMode = ref<ViewMode>("trajectory")
const trajectory = ref<Trajectory>()
const trace = ref<Trace>()
const selectedRunId = ref("")
const events = ref<Record<number, SessionEvent>>({})
const loading = ref(true)
const traceLoading = ref(false)
const errorMessage = ref("")
const detailErrors = ref<Record<number, string>>({})

const selectedRun = computed<TrajectoryRun | undefined>(() =>
  trajectory.value?.runs.find((run) => run.runId === selectedRunId.value),
)

function displayTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN", { hour12: false })
}

function stepTitle(step: TrajectoryStep): string {
  if (step.kind === "user_input") return step.summary
  if (step.kind === "model_call") return `模型调用（${step.status}）`
  return `状态变化：${step.from} → ${step.to}`
}

function stepSeqs(step: TrajectoryStep): number[] {
  if (step.kind === "model_call") return [step.requestSeq, ...(step.resultSeq === undefined ? [] : [step.resultSeq])]
  return [step.eventSeq]
}

async function loadTrajectory() {
  loading.value = true
  errorMessage.value = ""
  try {
    trajectory.value = await fetchSessionTrajectory(sessionId)
    selectedRunId.value = trajectory.value.runs[0]?.runId ?? ""
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function loadTrace() {
  if (!selectedRunId.value) return
  traceLoading.value = true
  errorMessage.value = ""
  try {
    trace.value = await fetchSessionTrace(sessionId, selectedRunId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    traceLoading.value = false
  }
}

async function showEvent(seq: number) {
  if (events.value[seq]) return
  detailErrors.value[seq] = ""
  try {
    events.value[seq] = await fetchSessionEvent(sessionId, seq)
  } catch (error) {
    detailErrors.value[seq] = error instanceof Error ? error.message : String(error)
  }
}

function eventJson(seq: number): string {
  return JSON.stringify(events.value[seq], null, 2)
}

function traceLabel(node: TraceNode): string {
  return `#${node.seq} ${node.eventType}`
}

onMounted(loadTrajectory)
watch(viewMode, (mode) => {
  if (mode === "trace") void loadTrace()
})
watch(selectedRunId, () => {
  trace.value = undefined
  if (viewMode.value === "trace") void loadTrace()
})
</script>

<template>
  <main class="log-page">
    <header class="log-header">
      <div>
        <p class="eyebrow">SESSION EVENT LOG</p>
        <h1>运行日志</h1>
        <p>session-{{ sessionId }} · 由 Event Log 投影得到</p>
      </div>
      <div class="log-actions">
        <RouterLink :to="`/sessions/${sessionId}`">返回会话</RouterLink>
      </div>
    </header>

    <p v-if="errorMessage" class="error-state">{{ errorMessage }}</p>
    <p v-if="loading" class="loading-state">正在读取运行轨迹……</p>

    <template v-else>
      <section class="view-panel" aria-label="日志视图">
        <div class="view-switch" role="tablist" aria-label="日志投影">
          <button type="button" :class="{ active: viewMode === 'trajectory' }" :aria-pressed="viewMode === 'trajectory'" @click="viewMode = 'trajectory'">Trajectory 运行步骤</button>
          <button type="button" :class="{ active: viewMode === 'trace' }" :aria-pressed="viewMode === 'trace'" @click="viewMode = 'trace'">Trace 因果关系</button>
        </div>
        <label class="run-picker">
          运行
          <select v-model="selectedRunId" :disabled="!trajectory?.runs.length">
            <option v-for="run in trajectory?.runs ?? []" :key="run.runId" :value="run.runId">{{ run.runId }}</option>
          </select>
        </label>
      </section>

      <section v-if="viewMode === 'trajectory'" class="content-section">
        <p v-if="!trajectory?.runs.length" class="empty-state">当前会话没有可展示的运行步骤。</p>
        <template v-else-if="selectedRun">
          <p class="section-note">开始时间：{{ displayTime(selectedRun.startedAt) }}</p>
          <ol class="step-list">
            <li v-for="step in selectedRun.steps" :key="`${step.kind}-${stepSeqs(step).join('-')}`" class="step-item">
              <div class="step-heading">
                <strong>{{ stepTitle(step) }}</strong>
                <span>{{ stepSeqs(step).map((seq) => `#${seq}`).join(' · ') }}</span>
              </div>
              <div class="step-meta">
                <span>{{ step.kind }}</span>
                <span v-if="step.kind === 'model_call' && step.durationMs !== undefined">耗时 {{ step.durationMs }} ms</span>
              </div>
              <details v-for="seq in stepSeqs(step)" :key="seq" class="event-detail" @toggle="showEvent(seq)">
                <summary>查看原始事件 #{{ seq }}</summary>
                <p v-if="detailErrors[seq]" class="detail-error">{{ detailErrors[seq] }}</p>
                <p v-else-if="!events[seq]" class="detail-loading">正在读取事件……</p>
                <template v-else>
                  <div class="event-meta"><span>{{ events[seq].eventType }}</span><time>{{ displayTime(events[seq].occurredAt) }}</time></div>
                  <pre>{{ eventJson(seq) }}</pre>
                </template>
              </details>
            </li>
          </ol>
        </template>
      </section>

      <section v-else class="content-section">
        <p v-if="traceLoading" class="loading-state">正在读取因果关系……</p>
        <p v-else-if="!trace?.roots.length" class="empty-state">当前运行没有可展示的因果节点。</p>
        <div v-else class="trace-tree"><TraceBranch v-for="node in trace.roots" :key="node.seq" :node="node" :events="events" :detail-errors="detailErrors" @show-event="showEvent" /></div>
      </section>
    </template>
  </main>
</template>

<script lang="ts">
import { defineComponent, h, type PropType, type VNode } from "vue"
import type { SessionEvent as SessionEventRecord, TraceNode as TraceTreeNode } from "../types/session-event"

const TraceBranch: ReturnType<typeof defineComponent> = defineComponent({
  name: "TraceBranch",
  props: {
    node: { type: Object as PropType<TraceTreeNode>, required: true },
    events: { type: Object as PropType<Record<number, SessionEventRecord>>, required: true },
    detailErrors: { type: Object as PropType<Record<number, string>>, required: true },
  },
  emits: ["show-event"],
  setup(props, { emit }): () => VNode {
    return () => h("details", { class: "trace-node", open: true }, [
      h("summary", { onClick: () => emit("show-event", props.node.seq) }, [
        h("strong", `#${props.node.seq} ${props.node.eventType}`),
        h("span", props.node.children.length ? `${props.node.children.length} 个子事件` : "叶节点"),
      ]),
      props.detailErrors[props.node.seq]
        ? h("p", { class: "detail-error" }, props.detailErrors[props.node.seq])
        : props.events[props.node.seq]
          ? h("pre", JSON.stringify(props.events[props.node.seq], null, 2))
          : h("p", { class: "detail-loading" }, "正在读取事件……"),
      ...props.node.children.map((child) => h(TraceBranch, {
        node: child,
        events: props.events,
        detailErrors: props.detailErrors,
        onShowEvent: (seq: number) => emit("show-event", seq),
      })),
    ])
  },
})

export default defineComponent({
  name: "SessionEventLogView",
  components: { TraceBranch },
})
</script>

<style scoped>
.log-page { width: min(100%, var(--content-width)); margin: 0 auto; padding: var(--space-8) var(--space-6) var(--space-12); }
.log-header, .view-panel, .view-switch, .step-heading, .step-meta, .event-meta { display: flex; align-items: center; gap: var(--space-3); }
.log-header, .view-panel, .step-heading { justify-content: space-between; }
.log-header { flex-wrap: wrap; margin-bottom: var(--space-6); }
.log-header h1 { margin: var(--space-1) 0; }
.log-header p { margin: 0; color: var(--color-text-secondary); }
.eyebrow { color: var(--color-brand-700) !important; font-size: 12px; letter-spacing: .1em; }
.log-actions a { color: var(--color-brand-700); }
.view-panel { flex-wrap: wrap; padding-bottom: var(--space-4); border-bottom: 1px solid var(--color-border); }
.view-switch { flex-wrap: wrap; }
.view-switch button { min-height: 40px; padding: 0 var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); color: var(--color-text-secondary); background: var(--color-surface); cursor: pointer; }
.view-switch button.active { border-color: var(--color-brand-700); color: var(--color-on-brand); background: var(--color-brand-700); }
.run-picker { display: flex; align-items: center; gap: var(--space-2); color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.run-picker select { min-width: 220px; min-height: 40px; padding: 0 var(--space-2); border: 1px solid var(--color-border-strong); border-radius: var(--radius-md); background: var(--color-surface); }
.content-section { margin-top: var(--space-6); }
.section-note, .loading-state, .empty-state { color: var(--color-text-muted); }
.step-list { display: grid; gap: var(--space-3); margin: 0; padding: 0; list-style: none; }
.step-item { padding: var(--space-4); border: 1px solid var(--color-border); border-left: 4px solid var(--color-brand-600); border-radius: var(--radius-md); background: var(--color-surface); }
.step-heading { align-items: flex-start; }
.step-heading strong { overflow-wrap: anywhere; }
.step-heading span, .step-meta, .event-meta { color: var(--color-text-muted); font-size: var(--font-size-sm); }
.step-meta { margin-top: var(--space-1); flex-wrap: wrap; }
.event-detail, .trace-node { margin-top: var(--space-3); padding-top: var(--space-3); border-top: 1px solid var(--color-border); }
.event-detail summary, .trace-node summary { cursor: pointer; color: var(--color-brand-700); }
.event-meta { justify-content: space-between; flex-wrap: wrap; margin: var(--space-3) 0; }
.event-meta time { color: var(--color-text-muted); }
pre { max-height: 480px; overflow: auto; margin: 0; padding: var(--space-3); border-radius: var(--radius-sm); color: #e5e7eb; background: #1f2937; font-size: 12px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
.detail-error { padding: var(--space-2); color: var(--color-error-700); background: var(--color-error-100); overflow-wrap: anywhere; }
.detail-loading { color: var(--color-text-muted); }
.trace-tree { display: grid; gap: var(--space-3); }
.trace-node { margin-top: 0; padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.trace-node > summary { display: flex; justify-content: space-between; gap: var(--space-3); }
.trace-node > summary span { color: var(--color-text-muted); font-size: var(--font-size-sm); }
.trace-node .trace-node { margin-top: var(--space-3); margin-left: var(--space-4); border-left: 3px solid var(--color-brand-100); }
.error-state { padding: var(--space-3); border-radius: var(--radius-md); color: var(--color-error-700); background: var(--color-error-100); overflow-wrap: anywhere; }
@media (max-width: 640px) {
  .log-page { padding: var(--space-6) var(--space-4) var(--space-8); }
  .log-header, .view-panel { align-items: flex-start; flex-direction: column; }
  .view-switch, .view-switch button, .run-picker, .run-picker select { width: 100%; }
  .view-switch button { text-align: left; }
  .step-heading { align-items: flex-start; flex-direction: column; gap: var(--space-1); }
  .trace-node .trace-node { margin-left: var(--space-2); }
}
</style>
