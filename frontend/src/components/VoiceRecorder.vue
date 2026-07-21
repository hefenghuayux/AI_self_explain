<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue"

const props = defineProps<{
  sessionId: string
  version: number
  disabled?: boolean
}>()

const emit = defineEmits<{
  finalTranscript: [text: string]
  completed: []
  recordingChange: [recording: boolean]
  error: [message: string]
}>()

const recording = ref(false)
const previewText = ref("")
let socket: WebSocket | undefined
let audioContext: AudioContext | undefined
let mediaStream: MediaStream | undefined
let sourceNode: MediaStreamAudioSourceNode | undefined
let processorNode: ScriptProcessorNode | undefined
let silentGainNode: GainNode | undefined
let targetSampleRate = 16000

function createVoiceStreamUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
  return `${protocol}//${window.location.host}/api/sessions/${props.sessionId}/voice-stream?version=${props.version}`
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

function finishRecording() {
  releaseMicrophone()
  recording.value = false
  emit("recordingChange", false)
}

async function start() {
  if (recording.value || props.disabled) return
  previewText.value = ""
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    socket = new WebSocket(createVoiceStreamUrl())
    socket.binaryType = "arraybuffer"
    socket.onmessage = (event) => {
      const message = JSON.parse(String(event.data)) as {
        type: string
        text?: string
        sampleRateHz?: number
        message?: string
      }
      if (message.type === "ready") {
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
        recording.value = true
        emit("recordingChange", true)
      } else if (message.type === "partial_transcript") {
        previewText.value = message.text ?? ""
      } else if (message.type === "final_transcript") {
        previewText.value = ""
        if (message.text) emit("finalTranscript", message.text)
      } else if (message.type === "completed") {
        finishRecording()
        emit("completed")
      } else if (message.type === "error") {
        finishRecording()
        emit("error", message.message ?? "实时语音识别失败")
      }
    }
    socket.onerror = () => {
      if (mediaStream) {
        finishRecording()
        emit("error", "无法连接实时语音识别服务")
      }
    }
    socket.onclose = () => {
      if (recording.value) finishRecording()
    }
  } catch (error) {
    finishRecording()
    emit("error", error instanceof Error ? error.message : String(error))
  }
}

function stop() {
  releaseMicrophone()
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "stop" }))
}

onBeforeUnmount(() => {
  releaseMicrophone()
  socket?.close()
})

defineExpose({ start })
</script>

<template>
  <section class="voice-recorder">
    <h3>实时语音输入</h3>
    <p>录音时仍可编辑上方文本；句末转写会追加到输入框，未确认前不会进入 AI 评价。</p>
    <p v-if="previewText" class="transcript-preview">正在转写：{{ previewText }}</p>
    <div class="actions">
      <el-button v-if="!recording" data-testid="start-voice" :disabled="disabled" @click="start">开始录音</el-button>
      <el-button v-else data-testid="stop-voice" type="danger" @click="stop">停止录音</el-button>
    </div>
  </section>
</template>

<style scoped>
.voice-recorder { margin-top: 16px; }
.voice-recorder h3 { margin: 0; }
.transcript-preview { color: #606266; }
.actions { display: flex; gap: 8px; margin-top: 12px; }
</style>
