import { getAuthToken } from "../stores/auth"

export type TeacherSpeechRequest = { itemIds: string[] } | { fullSolution: true }

export type TeacherSpeechFormat = {
  type: "format"
  sampleRate: 24000
  channels: 1
  encoding: "pcm_s16le"
}

export type TeacherSpeechChunk = TeacherSpeechFormat | { type: "audio"; data: Uint8Array }

export async function streamTeacherSpeech(
  sessionId: string,
  request: TeacherSpeechRequest,
  signal: AbortSignal,
  onChunk: (chunk: TeacherSpeechChunk) => void,
): Promise<void> {
  const token = getAuthToken()
  if (!token) throw new Error("请先登录后播放老师语音")
  const response = await fetch(`/api/sessions/${sessionId}/teacher-speech/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(request),
    signal,
  })
  if (!response.ok) {
    const body = await response.json() as { detail?: string | { message?: string } | Array<{ msg: string }> }
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => item.msg).join("；")
      : typeof body.detail === "string" ? body.detail : body.detail?.message
    throw new Error(detail ?? `语音生成失败：HTTP ${response.status}`)
  }
  if (!response.headers.get("Content-Type")?.toLowerCase().startsWith("application/x-ndjson") || !response.body) {
    throw new Error("语音服务未返回有效音频流")
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder("utf-8", { fatal: true })
  let pending = ""
  let formatted = false
  let receivedAudio = false
  let done = false
  const consume = (line: string) => {
    if (!line.trim()) return
    if (signal.aborted) throw new DOMException("语音请求已取消", "AbortError")
    const event = JSON.parse(line) as Record<string, unknown>
    if (event.type === "error") throw new Error(typeof event.message === "string" ? event.message : "语音流生成失败")
    if (event.type === "format" && !formatted && event.sampleRate === 24000 && event.channels === 1 && event.encoding === "pcm_s16le") {
      formatted = true
      onChunk(event as TeacherSpeechFormat)
    } else if (event.type === "audio" && formatted && typeof event.data === "string" && event.data.length > 0) {
      const bytes = Uint8Array.from(atob(event.data), (character) => character.charCodeAt(0))
      if (!bytes.length) throw new Error("语音服务返回了空音频块")
      receivedAudio = true
      onChunk({ type: "audio", data: bytes })
    } else if (event.type === "done" && formatted && receivedAudio) {
      done = true
    } else {
      throw new Error("语音流事件或音频格式无效")
    }
  }
  try {
    while (!done) {
      const result = await reader.read()
      pending += decoder.decode(result.value, { stream: !result.done })
      let newline: number
      while (!done && (newline = pending.indexOf("\n")) >= 0) {
        consume(pending.slice(0, newline))
        pending = pending.slice(newline + 1)
      }
      if (result.done) {
        if (!done && pending) consume(pending)
        if (!done) throw new Error("语音流意外中断，未收到完成标记")
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}

export async function fetchTeacherSpeech(
  sessionId: string,
  request: TeacherSpeechRequest,
  signal: AbortSignal,
): Promise<Blob> {
  const token = getAuthToken()
  if (!token) throw new Error("请先登录后播放老师语音")
  const response = await fetch(`/api/sessions/${sessionId}/teacher-speech`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(request),
    signal,
  })
  if (!response.ok) {
    const body = await response.json() as {
      detail?: string | { message?: string } | Array<{ msg: string }>
    }
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => item.msg).join("；")
      : typeof body.detail === "string" ? body.detail : body.detail?.message
    throw new Error(detail ?? `语音生成失败：HTTP ${response.status}`)
  }
  if (!response.headers.get("Content-Type")?.toLowerCase().startsWith("audio/")) {
    throw new Error("语音服务返回了非音频内容")
  }
  const audio = await response.blob()
  if (!audio.size) throw new Error("语音服务返回了空音频")
  return audio
}
