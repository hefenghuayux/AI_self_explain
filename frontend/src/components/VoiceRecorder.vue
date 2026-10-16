<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue"

import { getAuthToken } from "../stores/auth"
import type { VoiceInputTarget } from "../types/session"
import InputActionButton from "./InputActionButton.vue"

const props = withDefaults(defineProps<{
  sessionId: string
  version: number
  target: VoiceInputTarget
  targetId?: string
  startTestId?: string
  stopTestId?: string
  label?: string
  stopLabel?: string
  iconButton?: boolean
  inline?: boolean
  disabled?: boolean
  prepareStart?: () => Promise<boolean> | boolean
}>(), {
  startTestId: "start-voice",
  stopTestId: "stop-voice",
  label: "录音",
})

const emit = defineEmits<{
  finalTranscript: [text: string]
  completed: [payload: { attemptId: number; version: number }]
  recordingChange: [recording: boolean]
  busyChange: [busy: boolean]
  error: [message: string]
}>()

type VoiceState = "idle" | "connecting" | "recording" | "transcribing" | "completed" | "failed"
const state = ref<VoiceState>("idle")
const recording = computed(() => state.value === "recording")
const busy = computed(() => ["connecting", "recording", "transcribing"].includes(state.value))
const buttonLabel = computed(() => {
  if (props.iconButton || props.stopLabel) {
    if (state.value === "connecting") return "正在连接"
    if (state.value === "transcribing") return props.stopLabel ? "保存中" : "正在保存转写"
  }
  return recording.value ? (props.stopLabel ?? `停止${props.label}`) : props.label
})
const statusText = computed(() => ({
  idle: "",
  connecting: "正在准备录音并连接…",
  recording: props.target === "SELF_EXPLANATION_EXPLAIN" ? "正在自讲，点击暂停自讲保存本段。" : "正在录音，点击按钮停止。",
  transcribing: "正在完成转写，请稍候…",
  completed: props.target === "SELF_EXPLANATION_EXPLAIN"
    ? "本段讲解已保存，可继续自讲，提交时一并使用。"
    : "转写完成，请检查输入内容。",
  failed: "录音未完成，可重新尝试。",
})[state.value])
const previewText = ref("")
let disposed = false
let socket: WebSocket | undefined
let audioContext: AudioContext | undefined
let mediaStream: MediaStream | undefined
let sourceNode: MediaStreamAudioSourceNode | undefined
let processorNode: ScriptProcessorNode | undefined
let silentGainNode: GainNode | undefined
let targetSampleRate = 16000

function createVoiceStreamUrl() {
  const token = getAuthToken()
  if (!token) throw new Error("请先登录")
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
  const query = new URLSearchParams({
    version: String(props.version),
    target: props.target,
  })
  if (props.targetId) query.set("targetId", props.targetId)
  return {
    url: `${protocol}//${window.location.host}/api/sessions/${props.sessionId}/voice-stream?${query}`,
    token,
  }
}

function encodePcm16(input: Float32Array, sourceSampleRate: number) {
  const ratio = sourceSampleRate / targetSampleRate
  const outputLength = Math.floor(input.length / ratio)
  const output = new Int16Array(outputLength)
  for (let index = 0; index < outputLength; index += 1) {
    const sourceIndex = Math.min(Math.floor(index * ratio), input.length - 1)
    const sample = Math.max(-1, Math.min(1, input[sourceIndex]))
    output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
  }
  return output.buffer
}

function releaseMicrophone() {
  processorNode?.disconnect()
  sourceNode?.disconnect()
  silentGainNode?.disconnect()
  mediaStream?.getTracks().forEach((track) => track.stop())
  void audioContext?.close()
  processorNode = undefined
  sourceNode = undefined
  silentGainNode = undefined
  mediaStream = undefined
  audioContext = undefined
}

function setState(next: VoiceState) {
  const wasRecording = recording.value
  const wasBusy = busy.value
  state.value = next
  if (wasRecording !== recording.value) emit("recordingChange", recording.value)
  if (wasBusy !== busy.value) emit("busyChange", busy.value)
}

function releaseSocket() {
  if (!socket) return
  socket.onmessage = null
  socket.onerror = null
  socket.onclose = null
  socket.close()
  socket = undefined
}

function fail(message: string) {
  releaseMicrophone()
  releaseSocket()
  previewText.value = ""
  setState("failed")
  emit("error", message)
}

async function start() {
  if (disposed || busy.value || props.disabled) return
  setState("connecting")
  previewText.value = ""
  try {
    if (props.prepareStart && !(await props.prepareStart())) {
      if (!disposed) setState("idle")
      return
    }
    if (disposed) return
    const acquiredStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    if (disposed) {
      acquiredStream.getTracks().forEach((track) => track.stop())
      return
    }
    mediaStream = acquiredStream
    const voiceStream = createVoiceStreamUrl()
    socket = new WebSocket(voiceStream.url, ["bearer", voiceStream.token])
    socket.binaryType = "arraybuffer"
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(String(event.data)) as {
          type: string
          text?: string
          attemptId?: number
          version?: number
          sampleRateHz?: number
          message?: string
        }
        if (message.type === "ready") {
          if (state.value !== "connecting") return
          targetSampleRate = message.sampleRateHz ?? targetSampleRate
          audioContext = new AudioContext()
          sourceNode = audioContext.createMediaStreamSource(mediaStream!)
          processorNode = audioContext.createScriptProcessor(4096, 1, 1)
          silentGainNode = audioContext.createGain()
          silentGainNode.gain.value = 0
          processorNode.onaudioprocess = (audioEvent) => {
            if (socket?.readyState !== WebSocket.OPEN || !audioContext) return
            socket.send(encodePcm16(audioEvent.inputBuffer.getChannelData(0), audioContext.sampleRate))
          }
          sourceNode.connect(processorNode)
          processorNode.connect(silentGainNode)
          silentGainNode.connect(audioContext.destination)
          setState("recording")
        } else if (message.type === "partial_transcript") {
          previewText.value = message.text ?? ""
        } else if (message.type === "final_transcript") {
          previewText.value = ""
          if (message.text) emit("finalTranscript", message.text)
        } else if (message.type === "completed") {
          if (typeof message.attemptId !== "number") {
            fail("实时语音识别未返回语音尝试编号")
            return
          }
          if (typeof message.version !== "number") {
            fail("实时语音识别未返回最新会话版本")
            return
          }
          releaseMicrophone()
          releaseSocket()
          previewText.value = ""
          setState("completed")
          emit("completed", {
            attemptId: message.attemptId,
            version: message.version,
          })
        } else if (message.type === "error") {
          fail(message.message ?? "实时语音识别失败")
        }
      } catch (error) {
        fail(error instanceof Error ? error.message : String(error))
      }
    }
    socket.onerror = () => {
      fail("无法连接实时语音识别服务")
    }
    socket.onclose = () => {
      if (busy.value) fail("实时语音识别连接已断开，转写未完成")
    }
  } catch (error) {
    if (!disposed) fail(error instanceof Error ? error.message : String(error))
  }
}

function stop() {
  if (!recording.value) return
  const activeSocket = socket
  releaseMicrophone()
  setState("transcribing")
  if (activeSocket?.readyState === WebSocket.OPEN) {
    activeSocket.send(JSON.stringify({ type: "stop" }))
  } else {
    fail("实时语音识别连接已断开，转写未完成")
  }
}

onBeforeUnmount(() => {
  disposed = true
  releaseMicrophone()
  releaseSocket()
  setState("idle")
})

defineExpose({ start, stop })
</script>

<template>
  <section class="voice-recorder" :class="{ 'is-inline': inline, 'is-toolbar': inline && (iconButton || stopLabel) }">
    <div v-if="!inline" class="voice-heading">
      <span class="recording-indicator" :class="{ 'is-recording': recording }" aria-hidden="true"></span>
      <div><h3>{{ recording ? "正在录音" : "实时语音输入" }}</h3><p>句末转写会追加到输入框，确认前不会进入 AI 评价。</p></div>
    </div>
    <div class="actions">
      <InputActionButton v-if="iconButton" :icon="recording ? 'stop' : 'microphone'" :label="buttonLabel"
        :data-testid="recording ? stopTestId : startTestId" :type="recording ? 'danger' : undefined"
        :disabled="!recording && (disabled || busy)" :loading="busy && !recording"
        @click="recording ? stop() : start()" />
      <el-button
        v-else
        class="record-button"
        :data-testid="recording ? stopTestId : startTestId"
        :type="recording ? 'danger' : undefined"
        :disabled="!recording && (disabled || busy)"
        :loading="Boolean(stopLabel) && busy && !recording"
        :aria-pressed="recording"
        @click="recording ? stop() : start()"
      >{{ buttonLabel }}</el-button>
    </div>
    <p v-if="statusText" class="voice-status" role="status">{{ statusText }}</p>
    <p v-if="previewText" class="transcript-preview" aria-live="polite">正在转写：{{ previewText }}</p>
  </section>
</template>

<style scoped>
.voice-recorder { margin-top: var(--space-4); padding: var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-muted); }
.voice-heading { display: flex; align-items: flex-start; gap: var(--space-3); }
.recording-indicator { width: 12px; height: 12px; flex: 0 0 auto; margin-top: 7px; border: 2px solid var(--color-brand-600); border-radius: 50%; background: var(--color-surface); }
.recording-indicator.is-recording { border-color: var(--color-error-700); background: var(--color-error-700); }
.voice-recorder h3 { margin: 0; font-size: var(--font-size-base); }
.voice-recorder p { margin: var(--space-1) 0 0; color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.transcript-preview { padding: var(--space-3); border-radius: var(--radius-sm); background: var(--color-surface); }
.actions { display: flex; gap: var(--space-2); margin-top: var(--space-3); }
.voice-recorder.is-inline { margin-top: 0; padding: 0; border: 0; background: transparent; }
.voice-recorder.is-inline .actions { margin-top: 0; }
.voice-recorder.is-toolbar, .voice-recorder.is-toolbar .actions { display: contents; }
.voice-recorder.is-toolbar .record-button { width: 96px; height: 44px; flex: 0 0 96px; margin: 0; padding: 0; }
.voice-recorder.is-toolbar .voice-status, .voice-recorder.is-toolbar .transcript-preview { order: 1; flex: 1 0 100%; min-width: 0; overflow-wrap: anywhere; }
@media (max-width: 640px) { .actions .el-button { width: 100%; } }
</style>
