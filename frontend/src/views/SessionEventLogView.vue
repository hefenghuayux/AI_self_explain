<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import { useRoute } from "vue-router"

import EventDetails from "../components/EventDetails.vue"
import EventLedger from "../components/EventLedger.vue"
import EventTimeline from "../components/EventTimeline.vue"
import { fetchSessionTrajectory } from "../api/session-events"
import { scopeRecords, type TrajectoryScope } from "../utils/trajectoryScope"
import type { Trajectory, TrajectoryRecord } from "../types/session-event"

/** 账本按窗口渲染，只有点「加载更早的记录」才扩大窗口；默认展示尾部最新记录。 */
const LEDGER_WINDOW = 200
/** 超过该记录数时默认收起运行，避免首次进入就铺满整屏。 */
const AUTO_COLLAPSE_THRESHOLD = 40
/** 运行下拉里的“全部运行”：把整个会话的运行合并成一条按事件序排列的记录流。 */
const ALL_RUNS = "__all__"

const route = useRoute()
const sessionId = String(route.params.sessionId)
const trajectory = ref<Trajectory>()
const selectedRunId = ref(ALL_RUNS)
const selectedSeq = ref<number>()
const timelineMode = ref<"sequence" | "duration">("sequence")
const searchQuery = ref("")
/** 精简范围只显示上下文、用户与助手信息；完整范围追加状态变化与模型请求。 */
const ledgerScope = ref<TrajectoryScope>("core")
const collapsedRunIds = ref<ReadonlySet<string>>(new Set())
const ledgerWindow = ref(LEDGER_WINDOW)
const loading = ref(true)
const errorMessage = ref("")

const runs = computed(() => trajectory.value?.runs ?? [])

const allRunsSelected = computed(() => selectedRunId.value === ALL_RUNS)

const totalRecordCount = computed(() =>
  runs.value.reduce((total, run) => total + run.records.length, 0),
)

const selectedRun = computed(() =>
  runs.value.find((run) => run.runId === selectedRunId.value),
)

const runLabel = computed(() => {
  if (allRunsSelected.value) return "全部运行"
  const index = runs.value.findIndex((run) => run.runId === selectedRunId.value)
  return index < 0 ? "当前运行" : `第 ${index + 1} 次运行`
})

/**
 * 账本记录：单次运行取该运行的记录；全部运行把各运行按事件序拼起来。
 * 运行本身按首次出现的 seq 排序，运行内部也按 seq 排列，拼接后仍是全局事件序。
 */
const runRecords = computed<TrajectoryRecord[]>(() =>
  allRunsSelected.value
    ? runs.value.flatMap((run) => run.records)
    : (selectedRun.value?.records ?? []),
)

/** 全部运行没有单一 run，起止时间取最早一次运行，关键步骤数按所有运行累加。 */
const noteStartedAt = computed(() => selectedRun.value?.startedAt ?? runs.value[0]?.startedAt)

const noteStepCount = computed(() =>
  allRunsSelected.value
    ? runs.value.reduce((total, run) => total + run.steps.length, 0)
    : (selectedRun.value?.steps.length ?? 0),
)

/** 时间线与账本共用同一份范围规则，否则会留下点不到的色块（账本里那条已被隐藏）。 */
const timelineRecords = computed(() => scopeRecords(runRecords.value, ledgerScope.value))

const visibleRecords = computed<TrajectoryRecord[]>(() =>
  runRecords.value.slice(Math.max(0, runRecords.value.length - ledgerWindow.value)),
)

const hasOlderRecords = computed(() => visibleRecords.value.length < runRecords.value.length)

// 选中记录从整个运行里查，而不是当前账本窗口，避免窗口变化把详情面板挤掉。
const selectedRecord = computed<TrajectoryRecord | undefined>(() =>
  runRecords.value.find((record) => record.eventSeq === selectedSeq.value),
)

const runCollapsed = computed(() =>
  allRunsSelected.value
    ? allRunsCollapsed.value
    : collapsedRunIds.value.has(selectedRunId.value),
)

const collapsibleRuns = computed(() =>
  runs.value.filter((run) => run.records.length > 1).map((run) => run.runId),
)

const allRunsCollapsed = computed(
  () =>
    collapsibleRuns.value.length > 0 &&
    collapsibleRuns.value.every((runId) => collapsedRunIds.value.has(runId)),
)

function displayTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN", { hour12: false })
}

function selectRecord(seq: number) {
  selectedSeq.value = seq
}

function toggleRun(runId: string) {
  const next = new Set(collapsedRunIds.value)
  if (next.has(runId)) next.delete(runId)
  else next.add(runId)
  collapsedRunIds.value = next
}

function toggleAllRuns() {
  collapsedRunIds.value = allRunsCollapsed.value
    ? new Set()
    : new Set(collapsibleRuns.value)
}

/** 账本收起按钮在两种视图下的含义不同：单次运行收起自己，全部运行收起所有运行。 */
function toggleSelectedRun() {
  if (allRunsSelected.value) toggleAllRuns()
  else toggleRun(selectedRunId.value)
}

function loadOlder(): void {
  ledgerWindow.value += LEDGER_WINDOW
}

/** 切换运行后重置选中记录与账本窗口；记录多时默认收起，避免首次进入就铺满整屏。 */
function resetRunView() {
  selectedSeq.value = undefined
  ledgerWindow.value = LEDGER_WINDOW
  if (runRecords.value.length <= AUTO_COLLAPSE_THRESHOLD) {
    collapsedRunIds.value = new Set()
    return
  }
  collapsedRunIds.value = allRunsSelected.value
    ? new Set(collapsibleRuns.value)
    : new Set([selectedRunId.value])
}

async function loadTrajectory() {
  loading.value = true
  errorMessage.value = ""
  try {
    const result = await fetchSessionTrajectory(sessionId)
    trajectory.value = result
    // 默认落在最后一次运行：进入页面先看到最近一轮，而不是会话最早的那一轮。
    const latest = result.runs[result.runs.length - 1]
    selectedRunId.value = latest?.runId ?? ALL_RUNS
    resetRunView()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

onMounted(loadTrajectory)

watch(selectedRunId, resetRunView)

// 切回精简范围后，被隐藏记录的详情面板不该继续留着，否则面板与账本口径不一致。
watch(ledgerScope, () => {
  const seq = selectedSeq.value
  if (seq === undefined) return
  if (!timelineRecords.value.some((record) => record.eventSeq === seq)) selectedSeq.value = undefined
})
</script>

<template>
  <main class="log-page">
    <header class="log-header">
      <div>
        <p class="eyebrow">SESSION TRAJECTORY</p>
        <h1>运行轨迹</h1>
        <p>session-{{ sessionId }} · 由 Session Event Log 投影得到</p>
      </div>
      <div class="log-actions">
        <RouterLink :to="`/sessions/${sessionId}`">返回会话</RouterLink>
      </div>
    </header>

    <p v-if="errorMessage" class="error-state">{{ errorMessage }}</p>
    <p v-if="loading" class="loading-state">正在读取运行轨迹……</p>

    <template v-else-if="runs.length">
      <section class="toolbar" role="toolbar" aria-label="轨迹工具栏">
        <div class="toolbar-actions">
          <label class="run-picker">
            运行
            <select v-model="selectedRunId">
              <option v-for="(run, index) in runs" :key="run.runId" :value="run.runId">
                第 {{ index + 1 }} 次运行（{{ run.records.length }} 条记录）
              </option>
              <option :value="ALL_RUNS">全部运行（{{ totalRecordCount }} 条记录）</option>
            </select>
          </label>
          <label class="mode-toggle">
            <input v-model="timelineMode" type="radio" value="sequence" />
            等宽
          </label>
          <label class="mode-toggle">
            <input v-model="timelineMode" type="radio" value="duration" />
            按时长
          </label>
          <button type="button" class="toolbar-button" @click="toggleAllRuns">
            {{ allRunsCollapsed ? "展开所有运行" : "收起所有运行" }}
          </button>
          <button
            type="button"
            class="toolbar-button"
            :aria-pressed="ledgerScope === 'all'"
            @click="ledgerScope = ledgerScope === 'core' ? 'all' : 'core'"
          >
            {{ ledgerScope === "core" ? "显示完整日志" : "只看上下文与助手" }}
          </button>
        </div>
        <div class="toolbar-search">
          <input
            v-model="searchQuery"
            type="search"
            aria-label="搜索轨迹"
            placeholder="搜索类型、摘要或 #序号"
          />
        </div>
      </section>

      <EventTimeline
        :records="timelineRecords"
        :mode="timelineMode"
        :selected-seq="selectedSeq"
        @select="selectRecord"
      />

      <p v-if="noteStartedAt" class="section-note">
        {{ runLabel }} · 开始时间 {{ displayTime(noteStartedAt) }} ·
        共 {{ runRecords.length }} 条记录<template v-if="noteStepCount">
          ，其中 {{ noteStepCount }} 个关键步骤</template>
      </p>

      <div class="trajectory-split" :class="{ 'with-details': selectedRecord !== undefined }">
        <EventLedger
          :key="`${selectedRunId}-${ledgerScope}`"
          :records="visibleRecords"
          :run-label="runLabel"
          :scope="ledgerScope"
          :selected-seq="selectedSeq"
          :collapsed="runCollapsed"
          :search-query="searchQuery"
          :has-older-records="hasOlderRecords"
          @select="selectRecord"
          @toggle="toggleSelectedRun"
          @load-older="loadOlder"
        />
        <EventDetails
          v-if="selectedRecord"
          :key="selectedRecord.eventSeq"
          :record="selectedRecord"
          :session-id="sessionId"
          :records="visibleRecords"
          @close="selectedSeq = undefined"
          @select="selectRecord"
        />
      </div>
    </template>

    <p v-else class="empty-state">当前会话没有可展示的运行轨迹。</p>
  </main>
</template>

<style scoped>
.log-page { width: min(100%, var(--content-width)); margin: 0 auto; padding: var(--space-8) var(--space-6) var(--space-12); }
.log-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-6); }
.log-header h1 { margin: var(--space-1) 0; }
.log-header p { margin: 0; color: var(--color-text-secondary); }
.eyebrow { color: var(--color-brand-700) !important; font-size: 12px; letter-spacing: .1em; }
.log-actions a { color: var(--color-brand-700); }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-3); padding: var(--space-3) var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.toolbar-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); }
.run-picker { display: flex; align-items: center; gap: var(--space-2); color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.run-picker select { min-height: 34px; padding: 0 var(--space-2); border: 1px solid var(--color-border-strong); border-radius: var(--radius-md); background: var(--color-surface); font: inherit; }
.mode-toggle { display: flex; align-items: center; gap: var(--space-1); color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.toolbar-button { min-height: 34px; padding: 0 var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-md); color: var(--color-text-secondary); background: var(--color-surface); cursor: pointer; font: inherit; font-size: var(--font-size-sm); }
.toolbar-button:hover { border-color: var(--color-brand-700); color: var(--color-brand-700); }
.toolbar-search input { min-width: 240px; min-height: 34px; padding: 0 var(--space-3); border: 1px solid var(--color-border-strong); border-radius: var(--radius-md); background: var(--color-surface); font: inherit; font-size: var(--font-size-sm); }
.section-note { margin: var(--space-3) 0; color: var(--color-text-muted); font-size: var(--font-size-sm); }
.trajectory-split { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-4); margin-top: var(--space-4); align-items: start; }
.trajectory-split.with-details { grid-template-columns: minmax(0, 1fr) minmax(320px, 420px); }
.loading-state, .empty-state { color: var(--color-text-muted); }
.error-state { padding: var(--space-3); border-radius: var(--radius-md); color: var(--color-error-700); background: var(--color-error-100); overflow-wrap: anywhere; }
@media (max-width: 960px) {
  .trajectory-split.with-details { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 640px) {
  .log-page { padding: var(--space-6) var(--space-4) var(--space-8); }
  .log-header { align-items: flex-start; flex-direction: column; }
  .toolbar, .toolbar-actions { align-items: stretch; flex-direction: column; }
  .run-picker, .run-picker select, .toolbar-search input { width: 100%; }
  .toolbar-search input { min-width: 0; }
}
</style>
