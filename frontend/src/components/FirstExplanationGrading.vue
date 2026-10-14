<script setup lang="ts">
import { computed, ref, watch } from "vue"
import type { Grading } from "../types/grading"

const props = defineProps<{ grading: Grading | null; retrying?: boolean; submissionText?: string }>()
const emit = defineEmits<{ retry: []; acknowledge: []; open: [] }>()
const dialogOpen = ref(false)
const visible = computed(() => Boolean(props.grading))
const isPending = computed(() => props.grading?.status === "PENDING" || props.grading?.status === "RUNNING")
const isFailed = computed(() => props.grading?.status === "FAILED")
const report = computed(() => props.grading?.report)
const score = computed(() => report.value?.totalScore.toFixed(1) ?? "—")
const correctnessLevels = ["无可保留的相关正确内容", "仅保留零散正确内容", "关键环节有实质错误", "主要方法成立，有局部错误", "未发现实质错误"]
const completenessLevels = ["未表达可识别的必要内容", "仅交代孤立的局部内容", "多个方面已交代，核心内容有缺失", "核心已交代，有局部内容缺失", "全部必要内容已交代"]

function isEditing() {
  const active = document.activeElement
  return active instanceof HTMLElement && (active.isContentEditable || ["INPUT", "TEXTAREA"].includes(active.tagName))
}
watch(() => [props.grading?.id, props.grading?.status], () => {
  if (props.grading && !props.grading.acknowledgedAt && !isEditing() && ["SUCCEEDED", "FAILED"].includes(props.grading.status)) dialogOpen.value = true
}, { immediate: true })
function acknowledge() { dialogOpen.value = false; emit("acknowledge") }
function returnToSession() { if (isPending.value) { dialogOpen.value = false; return }; acknowledge() }
function openReport() { dialogOpen.value = true; emit("open") }
function retry() { dialogOpen.value = true; emit("retry") }
function beforeClose(done: () => void) { dialogOpen.value = false; done() }
function levelDescription(kind: "correctness" | "completeness", value: number) { return (kind === "correctness" ? correctnessLevels : completenessLevels)[value] || "" }
</script>

<template>
  <section v-if="grading" class="grading-entry" :class="{ 'grading-entry--failed': isFailed }" aria-live="polite">
    <div class="grading-entry__icon" aria-hidden="true">{{ isFailed ? "!" : isPending ? "…" : "✓" }}</div>
    <div class="grading-entry__copy"><strong v-if="isPending">首次自讲正在评分</strong><strong v-else-if="isFailed">首次自讲评分暂未完成</strong><strong v-else>首次自讲评分已完成</strong><p v-if="isPending">评分在后台进行，你可以继续输入。</p><p v-else-if="isFailed">{{ grading.errorMessage || "评分服务暂时不可用。" }}</p><p v-else>总分 {{ score }} 分{{ grading.evaluationStatus === 'RUNNING' || grading.evaluationStatus === 'PENDING' ? " · 自讲评价仍在生成" : " · 评分结果已保留" }}</p></div>
    <el-button v-if="isFailed" data-testid="retry-grading-entry" text type="primary" :loading="retrying" @click="retry">重新评分</el-button>
    <el-button v-else-if="!isPending" data-testid="view-grading-entry" text type="primary" @click="openReport">查看评价</el-button>
  </section>
  <el-dialog :model-value="visible && dialogOpen" width="min(800px, calc(100vw - 32px))" class="grading-dialog" :close-on-click-modal="false" :close-on-press-escape="true" :show-close="true" destroy-on-close aria-label="自讲评价" :before-close="beforeClose">
    <template #header><div class="grading-dialog__header"><span class="grading-dialog__mark" aria-hidden="true">▤</span><div><h2>自讲评价</h2><p>本次提交 · 第一次自讲</p></div></div></template>
    <div v-if="isPending" class="grading-dialog__pending" role="status"><span class="grading-spinner" aria-hidden="true" /><h3>正在评价首次自讲</h3><p>评分正在后台进行。你可以先返回自讲继续学习。</p><el-button data-testid="acknowledge-grading-pending" @click="returnToSession">返回自讲</el-button></div>
    <div v-else-if="isFailed" class="grading-dialog__pending" role="alert"><span class="grading-error-mark" aria-hidden="true">!</span><h3>暂时未能生成评价</h3><p>{{ grading?.errorMessage || "评分服务暂时不可用。" }}</p><div><el-button data-testid="acknowledge-grading-failed" @click="returnToSession">返回自讲</el-button><el-button data-testid="retry-grading-dialog" type="primary" :loading="retrying" @click="retry">重新评分</el-button></div></div>
    <div v-else-if="report" class="grading-dialog__body">
      <div class="grading-result__hero"><div class="grading-result__score"><span>自讲总分</span><strong>{{ score }}</strong><small>满分 100 分</small></div><p>{{ report.summary }}</p></div>
      <p class="grading-dialog__scope">依据首次提交的文字、公式与语音转写评价。评分只反映首次提交的表现，不代表长期掌握。</p>
      <div class="grading-result__dimensions">
        <article><header><h3>正确性</h3><strong>{{ report.correctnessScore }} / 4</strong></header><p class="grading-result__question">已表达的内容是否成立 · 占 50%</p><div class="grading-level-track" aria-hidden="true"><i v-for="index in 4" :key="index" :class="{ filled: index <= report.correctnessScore }" /></div><p class="grading-level-description">{{ levelDescription('correctness', report.correctnessScore) }}</p><div class="grading-result__reason"><strong>评价依据</strong><p>{{ report.correctnessReason }}</p></div></article>
        <article><header><h3>完整性</h3><strong>{{ report.completenessScore }} / 4</strong></header><p class="grading-result__question">本题必要内容是否覆盖 · 占 50%</p><div class="grading-level-track" aria-hidden="true"><i v-for="index in 4" :key="index" :class="{ filled: index <= report.completenessScore }" /></div><p class="grading-level-description">{{ levelDescription('completeness', report.completenessScore) }}</p><div class="grading-result__reason"><strong>评价依据</strong><p>{{ report.completenessReason }}</p></div></article>
      </div>
      <section v-if="report.missingRequirements.length" class="grading-missing"><h3>尚未表达的必要内容</h3><ul><li v-for="item in report.missingRequirements" :key="item">{{ item }}</li></ul></section>
      <p v-else class="grading-no-missing">✓ 本题必要内容已覆盖。</p>
      <details v-if="report.ambiguityNotes.length || report.rubricLimitations.length" class="grading-details grading-details--notice"><summary>查看评价说明</summary><div v-for="note in report.ambiguityNotes" :key="note.source"><h4>{{ note.source }}</h4><p>{{ note.interpretation }}（{{ note.impact }}）</p></div><div v-if="report.rubricLimitations.length"><h4>判据限制</h4><p v-for="item in report.rubricLimitations" :key="item">{{ item }}</p></div><p class="grading-details__footnote">识别歧义和判据限制不额外扣分。</p></details>
      <details class="grading-details"><summary>评分标准与总分计算</summary><div class="grading-rubric"><p>总分 =（正确性 + 完整性）÷ 8 × 100 = {{ score }} 分</p><table><thead><tr><th>档位</th><th>正确性</th><th>完整性</th></tr></thead><tbody><tr v-for="index in 5" :key="index"><td>{{ index - 1 }}</td><td>{{ correctnessLevels[index - 1] }}</td><td>{{ completenessLevels[index - 1] }}</td></tr></tbody></table><p>两项均为 0～4 整数档，总分不自动用于跨题比较，也不决定学习完成或掌握度。</p></div></details>
      <details class="grading-details"><summary>查看本次提交原文</summary><div class="grading-evidence">{{ submissionText || "首次提交原文暂不可用。" }}</div></details>
    </div>
    <template #footer><el-button data-testid="acknowledge-grading" type="primary" @click="returnToSession">返回自讲</el-button></template>
  </el-dialog>
</template>

<style scoped>
.grading-entry{display:flex;align-items:center;gap:var(--space-3);margin:var(--space-4) 0;padding:var(--space-3) var(--space-4);border:1px solid var(--color-brand-100);border-radius:var(--radius-lg);background:var(--color-brand-50)}.grading-entry--failed{border-color:var(--color-error-100);background:#fff7f6}.grading-entry__icon{display:grid;place-items:center;width:36px;height:36px;flex:none;border-radius:50%;color:var(--color-brand-700);background:var(--color-surface);font-weight:700}.grading-entry__copy{flex:1;min-width:0}.grading-entry__copy p{margin:0;color:var(--color-text-secondary);font-size:var(--font-size-sm)}.grading-dialog__header{display:flex;align-items:center;gap:var(--space-3)}.grading-dialog__header h2,.grading-dialog__header p{margin:0}.grading-dialog__header p,.grading-dialog__scope{color:var(--color-text-muted);font-size:var(--font-size-sm)}.grading-dialog__mark{display:grid;place-items:center;width:40px;height:40px;border-radius:var(--radius-md);color:var(--color-brand-700);background:var(--color-brand-50)}.grading-dialog__body{max-height:calc(100dvh - 220px);overflow-y:auto;padding-right:var(--space-2)}.grading-dialog__scope{margin:var(--space-4) 0 0}.grading-dialog__pending{display:grid;justify-items:center;gap:var(--space-3);padding:var(--space-8) var(--space-4);text-align:center}.grading-dialog__pending h3,.grading-dialog__pending p{margin:0}.grading-spinner{width:28px;height:28px;border:3px solid var(--color-brand-100);border-top-color:var(--color-brand-700);border-radius:50%;animation:grading-spin 800ms linear infinite}.grading-error-mark{display:grid;place-items:center;width:28px;height:28px;border-radius:50%;color:var(--color-error-700);background:var(--color-error-100);font-weight:700}@keyframes grading-spin{to{transform:rotate(360deg)}}.grading-result__hero{display:grid;grid-template-columns:160px 1fr;gap:var(--space-5);align-items:center}.grading-result__score{display:grid;justify-items:center;padding:var(--space-4);border:1px solid var(--color-brand-100);border-radius:var(--radius-lg);color:var(--color-brand-700);background:var(--color-brand-50)}.grading-result__score strong{font-size:42px}.grading-result__dimensions{display:grid;grid-template-columns:1fr 1fr;gap:var(--space-4);margin-top:var(--space-5)}.grading-result__dimensions article{padding:var(--space-4);border:1px solid var(--color-border);border-radius:var(--radius-md)}.grading-result__dimensions header{display:flex;justify-content:space-between}.grading-result__question{color:var(--color-text-muted);font-size:var(--font-size-sm)}.grading-level-track{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin:var(--space-3) 0}.grading-level-track i{height:6px;border-radius:3px;background:var(--color-border)}.grading-level-track i.filled{background:var(--color-brand-600)}.grading-level-description{min-height:42px;margin:0;font-weight:600}.grading-result__reason{margin-top:var(--space-3);padding-top:var(--space-3);border-top:1px solid var(--color-border);color:var(--color-text-secondary);font-size:var(--font-size-sm);line-height:1.75}.grading-result__reason strong{color:var(--color-brand-700);font-size:12px}.grading-result__reason p{margin:var(--space-2) 0 0}.grading-missing{margin-top:var(--space-4);padding:var(--space-3) var(--space-4);border:1px solid #f0ddc4;border-radius:var(--radius-md);background:#fff7ec;color:#633b1d}.grading-missing h3{margin:0;color:#9a4c10;font-size:var(--font-size-sm)}.grading-no-missing{margin:var(--space-4) 0;color:var(--color-text-secondary);font-size:var(--font-size-sm)}.grading-details{margin-top:var(--space-4);border-top:1px solid var(--color-border);padding-top:var(--space-2)}.grading-details summary{min-height:44px;display:flex;align-items:center;cursor:pointer;color:var(--color-text-secondary);font-size:var(--font-size-sm)}.grading-details summary::after{content:"+";margin-left:auto;font-size:20px}.grading-details[open] summary::after{content:"−"}.grading-details--notice{padding:var(--space-2) var(--space-3);border:1px solid #e5d5b5;border-radius:var(--radius-md);background:#fffcf5}.grading-details h4{margin:var(--space-2) 0 0;font-size:var(--font-size-sm)}.grading-details p{margin:var(--space-2) 0;color:var(--color-text-secondary);font-size:var(--font-size-sm)}.grading-details__footnote{padding-bottom:var(--space-2)}.grading-rubric{color:var(--color-text-secondary);font-size:var(--font-size-sm)}.grading-rubric table{width:100%;border-collapse:collapse;font-size:12px}.grading-rubric th,.grading-rubric td{padding:var(--space-2);border-bottom:1px solid var(--color-border);text-align:left;vertical-align:top}.grading-rubric th{color:var(--color-text-primary)}.grading-evidence{margin:var(--space-2) 0 var(--space-3);padding:var(--space-3);border-radius:var(--radius-md);background:var(--color-surface-muted);white-space:pre-wrap;overflow-wrap:anywhere;font-size:var(--font-size-sm)}
@media(max-width:640px){.grading-dialog__body{max-height:calc(100dvh - 190px)}.grading-result__hero,.grading-result__dimensions{grid-template-columns:1fr}.grading-result__hero{gap:var(--space-3)}.grading-result__score{justify-self:start;width:132px}.grading-entry{flex-wrap:wrap}.grading-entry__copy{min-width:calc(100% - 52px)}.grading-entry .el-button{margin-left:48px}.grading-rubric{overflow-x:auto}.grading-rubric table{min-width:520px}}
</style>
