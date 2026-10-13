<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue"

import { fetchTeacherSpeech, type TeacherSpeechRequest } from "../api/teacher-speech"

const props = withDefaults(defineProps<{
  sessionId: string
  itemIds: string[]
  disabled?: boolean
}>(), { disabled: false })

type SpeechState = "idle" | "preparing" | "playing" | "paused" | "ended" | "blocked" | "failed"
const preferenceKey = "ai-self-explain:teacher-speech:auto-play"
const autoPlay = ref(localStorage.getItem(preferenceKey) !== "false")
const state = ref<SpeechState>("idle")
const errorMessage = ref("")
const selectedRequest = ref<TeacherSpeechRequest>({ itemIds: [...props.itemIds] })
const hasTarget = computed(() => "fullSolution" in selectedRequest.value || selectedRequest.value.itemIds.length > 0)
let requestController: AbortController | undefined
let generation = 0
let audio: HTMLAudioElement | undefined
let audioUrl: string | undefined
let cachedAudio: { key: string; blob: Blob } | undefined

const statusText = computed(() => {
  if (props.disabled) return "当前操作期间已停止语音"
  const labels: Record<SpeechState, string> = {
    idle: hasTarget.value ? "老师语音已停止，可点击播放" : "等待老师回复",
    preparing: "正在准备语音…",
    playing: "老师正在说话",
    paused: "语音已暂停",
    ended: "语音播放结束",
    blocked: "浏览器阻止了自动播放，请点击播放",
    failed: "语音生成或播放失败",
  }
  return labels[state.value]
})
const playLabel = computed(() => {
  if (state.value === "paused") return "继续播放"
  if (state.value === "ended") return "重播"
  if (state.value === "failed") return "重试"
  return "播放语音"
})

function releaseAudio() {
  if (audio) {
    audio.onended = null
    audio.onerror = null
    audio.pause()
    audio.removeAttribute("src")
    audio = undefined
  }
  if (audioUrl) URL.revokeObjectURL(audioUrl)
  audioUrl = undefined
}

function stop() {
  generation += 1
  requestController?.abort()
  requestController = undefined
  releaseAudio()
  state.value = "idle"
  errorMessage.value = ""
}

async function startPlayback(activeAudio: HTMLAudioElement, requestGeneration: number) {
  try {
    await activeAudio.play()
    if (requestGeneration !== generation || activeAudio !== audio) {
      activeAudio.pause()
      return
    }
    state.value = "playing"
    errorMessage.value = ""
  } catch (error) {
    if (requestGeneration !== generation || activeAudio !== audio) return
    if ((error instanceof DOMException || error instanceof Error) && error.name === "NotAllowedError") {
      state.value = "blocked"
    } else {
      state.value = "failed"
      errorMessage.value = error instanceof Error ? error.message : String(error)
      releaseAudio()
    }
  }
}

async function synthesizeAndPlay() {
  if (props.disabled || !hasTarget.value) return
  stop()
  const requestGeneration = generation
  const request = selectedRequest.value
  const key = `${props.sessionId}:${JSON.stringify(request)}`
  const controller = new AbortController()
  requestController = controller
  state.value = "preparing"
  try {
    const blob = cachedAudio?.key === key
      ? cachedAudio.blob
      : await fetchTeacherSpeech(props.sessionId, request, controller.signal)
    if (requestGeneration !== generation) return
    cachedAudio = { key, blob }
    requestController = undefined
    audioUrl = URL.createObjectURL(blob)
    const activeAudio = new Audio(audioUrl)
    audio = activeAudio
    activeAudio.onended = () => {
      if (requestGeneration === generation) state.value = "ended"
    }
    activeAudio.onerror = () => {
      if (requestGeneration !== generation) return
      state.value = "failed"
      errorMessage.value = "音频加载或解码失败，请重试"
      cachedAudio = undefined
      releaseAudio()
    }
    await startPlayback(activeAudio, requestGeneration)
  } catch (error) {
    if (requestGeneration !== generation) return
    requestController = undefined
    state.value = "failed"
    errorMessage.value = error instanceof Error ? error.message : String(error)
  }
}

async function playReply(ids: string[], auto = true) {
  stop()
  selectedRequest.value = { itemIds: [...ids] }
  if (auto && !autoPlay.value) return
  await synthesizeAndPlay()
}

async function playSolution() {
  stop()
  selectedRequest.value = { fullSolution: true }
  await synthesizeAndPlay()
}

async function play() {
  if (props.disabled) return
  if (audio && (state.value === "paused" || state.value === "blocked")) {
    await startPlayback(audio, generation)
  } else {
    await synthesizeAndPlay()
  }
}

function pause() {
  audio?.pause()
  state.value = "paused"
}

watch(autoPlay, (enabled) => {
  localStorage.setItem(preferenceKey, String(enabled))
  if (!enabled) stop()
})
watch(() => props.itemIds, (ids, previousIds) => {
  if (ids.length === previousIds.length && ids.every((id, index) => id === previousIds[index])) return
  stop()
  selectedRequest.value = { itemIds: [...ids] }
}, { deep: true })
watch(() => props.disabled, (disabled) => {
  if (disabled) stop()
})
watch(() => props.sessionId, () => {
  stop()
  cachedAudio = undefined
})
onBeforeUnmount(stop)

defineExpose({ playReply, playSolution, stop })
</script>

<template>
  <section class="teacher-speech" aria-label="老师语音">
    <div class="speech-heading">
      <strong>老师语音</strong>
      <label class="auto-play-label">
        <input v-model="autoPlay" data-testid="teacher-speech-auto-play" type="checkbox" />
        自动播放老师回复
      </label>
    </div>
    <div class="speech-controls">
      <p data-testid="teacher-speech-status" role="status" aria-live="polite">{{ statusText }}</p>
      <el-button
        v-if="state === 'playing'"
        data-testid="teacher-speech-pause"
        :disabled="disabled"
        @click="pause"
      >暂停</el-button>
      <el-button
        v-else
        data-testid="teacher-speech-play"
        :disabled="disabled || !hasTarget || state === 'preparing'"
        :loading="state === 'preparing'"
        @click="play"
      >{{ playLabel }}</el-button>
      <el-button
        v-if="state === 'preparing' || state === 'playing' || state === 'paused'"
        data-testid="teacher-speech-stop"
        @click="stop"
      >停止</el-button>
    </div>
    <p v-if="errorMessage" class="speech-error" role="alert">{{ errorMessage }}</p>
  </section>
</template>

<style scoped>
.teacher-speech { margin-top: var(--space-4); padding: var(--space-3) var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface); }
.speech-heading, .speech-controls { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
.speech-heading { justify-content: space-between; }
.auto-play-label { display: inline-flex; align-items: center; min-height: 44px; gap: var(--space-2); cursor: pointer; color: var(--color-text-secondary); }
.auto-play-label input { width: 18px; height: 18px; accent-color: var(--color-brand-600); }
.speech-controls p { margin: 0; flex: 1 1 200px; color: var(--color-text-secondary); }
.speech-controls .el-button { min-height: 44px; margin-left: 0; }
.speech-error { margin: var(--space-2) 0 0; color: var(--color-error-700); overflow-wrap: anywhere; }
@media (max-width: 560px) {
  .speech-heading { align-items: flex-start; flex-direction: column; }
  .speech-controls p { flex-basis: 100%; }
}
</style>
