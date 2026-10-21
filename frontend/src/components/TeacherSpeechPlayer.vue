<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"

import { streamTeacherSpeech, type TeacherSpeechRequest } from "../api/teacher-speech"
import { TeacherSpeechPlayback, type SpeechPlaybackState } from "../services/teacher-speech-playback"
import { teacherSpeechAutoPlay as autoPlay, teacherSpeechVoiceVersion } from "../stores/teacherSpeech"

const props = withDefaults(defineProps<{
  sessionId: string
  itemIds: string[]
  disabled?: boolean
  controlsTarget?: string
  fullSolution?: boolean
}>(), { disabled: false })

type SpeechState = "idle" | SpeechPlaybackState | "failed"
const state = ref<SpeechState>("idle")
const errorMessage = ref("")
const selectedRequest = ref<TeacherSpeechRequest>(props.fullSolution
  ? { fullSolution: true } : { itemIds: [...props.itemIds] })
const hasTarget = computed(() => "fullSolution" in selectedRequest.value || selectedRequest.value.itemIds.length > 0)
let requestController: AbortController | undefined
let generation = 0
let context: AudioContext | undefined
let playback: TeacherSpeechPlayback | undefined
let cachedAudio: { key: string; chunks: Uint8Array[] } | undefined

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
  if (state.value === "playing") return "暂停语音"
  if (state.value === "preparing") return "正在准备语音"
  return "播放语音"
})

function getAudioContext() {
  if (!context) {
    const AudioContextClass = window.AudioContext
      ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!AudioContextClass) throw new Error("当前浏览器不支持流式语音播放")
    context = new AudioContextClass()
  }
  return context
}

// Unlock in the original user gesture, before recording/submission and network awaits.
function unlockAudio(event: Event) {
  if (!event.isTrusted || (playback && state.value === "paused")) return
  try {
    void getAudioContext().resume().catch(() => undefined)
  } catch {
    // Unsupported browsers report a visible error when playback is requested.
  }
}
const unlockEvents = ["pointerdown", "touchend", "keydown"] as const
onMounted(() => {
  for (const event of unlockEvents) document.addEventListener(event, unlockAudio, { capture: true, passive: true })
})

function stop() {
  generation += 1
  requestController?.abort()
  requestController = undefined
  playback?.stop()
  playback = undefined
  state.value = "idle"
  errorMessage.value = ""
}

function fail(error: unknown, requestGeneration: number) {
  if (requestGeneration !== generation) return
  requestController?.abort()
  requestController = undefined
  playback?.stop()
  playback = undefined
  cachedAudio = undefined
  state.value = "failed"
  errorMessage.value = error instanceof Error ? error.message : String(error)
}

async function synthesizeAndPlay() {
  if (props.disabled || !hasTarget.value) return
  stop()
  const requestGeneration = generation
  const request = selectedRequest.value
  const key = JSON.stringify([props.sessionId, request, teacherSpeechVoiceVersion.value])
  state.value = "preparing"
  try {
    const activePlayback = new TeacherSpeechPlayback(getAudioContext(), (nextState) => {
      if (requestGeneration === generation) state.value = nextState
    })
    playback = activePlayback
    // Initiate resume before the first network await. A blocked resume must not hold up streaming.
    void activePlayback.resume().catch((error) => fail(error, requestGeneration))
    if (cachedAudio?.key === key) {
      for (const chunk of cachedAudio.chunks) activePlayback.append(chunk)
      activePlayback.finish()
      return
    }
    cachedAudio = undefined
    const chunks: Uint8Array[] = []
    const controller = new AbortController()
    requestController = controller
    await streamTeacherSpeech(props.sessionId, request, controller.signal, (chunk) => {
      if (requestGeneration !== generation) return
      if (chunk.type === "audio") {
        chunks.push(chunk.data)
        activePlayback.append(chunk.data)
      }
    })
    if (requestGeneration !== generation) return
    requestController = undefined
    activePlayback.finish()
    cachedAudio = { key, chunks }
  } catch (error) {
    fail(error, requestGeneration)
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
  if (playback && (state.value === "paused" || state.value === "blocked")) {
    const requestGeneration = generation
    try {
      await playback.resume()
    } catch (error) {
      fail(error, requestGeneration)
    }
  } else {
    await synthesizeAndPlay()
  }
}

async function pause() {
  const requestGeneration = generation
  try {
    await playback?.pause()
  } catch (error) {
    fail(error, requestGeneration)
  }
}

watch(autoPlay, (enabled) => {
  if (!enabled) stop()
})
watch(() => props.itemIds, (ids, previousIds) => {
  if (ids.length === previousIds.length && ids.every((id, index) => id === previousIds[index])) return
  stop()
  selectedRequest.value = props.fullSolution ? { fullSolution: true } : { itemIds: [...ids] }
}, { deep: true })
watch(() => props.fullSolution, (fullSolution) => {
  stop()
  selectedRequest.value = fullSolution ? { fullSolution: true } : { itemIds: [...props.itemIds] }
})
watch(() => props.disabled, (disabled) => {
  if (disabled) stop()
})
watch(() => props.sessionId, () => { stop(); cachedAudio = undefined })
watch(teacherSpeechVoiceVersion, () => { stop(); cachedAudio = undefined }, { flush: "sync" })
onBeforeUnmount(() => {
  stop()
  cachedAudio = undefined
  for (const event of unlockEvents) document.removeEventListener(event, unlockAudio, { capture: true })
  void context?.close().catch(() => undefined)
})

defineExpose({ playReply, playSolution, stop })
</script>

<template>
  <Teleport :to="controlsTarget || 'body'" :disabled="!controlsTarget">
    <span v-show="hasTarget" class="teacher-speech" aria-label="老师语音">
      <button
        type="button"
        :data-testid="state === 'playing' ? 'teacher-speech-pause' : 'teacher-speech-play'"
        class="speech-toggle"
        :class="{ 'is-playing': state === 'playing', 'is-loading': state === 'preparing' }"
        :aria-label="playLabel"
        :title="state === 'failed' ? errorMessage : state === 'blocked' ? statusText : playLabel"
        :aria-busy="state === 'preparing'"
        :disabled="disabled || !hasTarget || state === 'preparing'"
        @click="state === 'playing' ? pause() : play()"
      >
        <svg v-if="state === 'preparing'" class="speech-spinner" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /></svg>
        <svg v-else-if="state === 'playing'" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7zM14 5h4v14h-4z" /></svg>
        <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M8 4.5v15L20 12z" /></svg>
      </button>
      <span data-testid="teacher-speech-status" class="speech-status" role="status" aria-live="polite">{{ statusText }}</span>
      <span v-if="state === 'blocked' || state === 'failed'" class="speech-message" role="alert">{{ errorMessage || statusText }}</span>
    </span>
  </Teleport>
</template>

<style scoped>
.teacher-speech { display: inline-flex; min-width: 0; max-width: 100%; flex-wrap: wrap; align-items: center; gap: var(--space-2); vertical-align: middle; }
.speech-toggle { display: inline-grid; place-items: center; width: 44px; height: 44px; padding: 10px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); color: var(--color-brand-700); background: var(--color-surface); cursor: pointer; flex-shrink: 0; transition: background-color var(--transition-interactive), border-color var(--transition-interactive); }
.speech-toggle svg { width: 22px; height: 22px; fill: currentColor; }
.speech-toggle:hover:not(:disabled), .speech-toggle.is-playing { border-color: var(--color-brand-700); background: var(--color-brand-50); }
.speech-toggle:focus-visible { outline: 3px solid var(--color-focus-ring); outline-offset: 2px; }
.speech-toggle:disabled { cursor: default; opacity: .55; }
.speech-spinner { animation: speech-spin 1s linear infinite; fill: none !important; stroke: currentColor; stroke-width: 2; stroke-dasharray: 42 16; }
.speech-status { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.speech-message { max-width: 240px; color: var(--color-error-700); font-size: var(--font-size-sm); overflow-wrap: anywhere; }
@keyframes speech-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .speech-spinner { animation: none; } }
</style>
