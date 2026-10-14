import { getAuthToken } from "../stores/auth"

export interface AIStreamChannel {
  generation: number
  status: "GENERATING" | "VALIDATED" | "FAILED"
  fields: Record<string, string>
}

export interface AIRunSnapshot<T = unknown> {
  runId: string
  status: "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED"
  revision: number
  channels: Record<string, AIStreamChannel>
  result: T | null
  error: { code: string; message: string; status: number } | null
}

export class AIStreamError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) {
    super(message)
    this.name = "AIStreamError"
  }
}

type SnapshotListener = (snapshot: AIRunSnapshot) => void
const listeners = new Map<string, Set<SnapshotListener>>()

export function registerAIStreamListener(sessionId: string, runId: string, listener: SnapshotListener) {
  const key = `${sessionId}:${runId}`
  const callbacks = listeners.get(key) ?? new Set<SnapshotListener>()
  callbacks.add(listener)
  listeners.set(key, callbacks)
  return () => {
    callbacks.delete(listener)
    if (!callbacks.size) listeners.delete(key)
  }
}

function reconnectDelay(signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const onAbort = () => { clearTimeout(timer); reject(signal?.reason ?? new DOMException("Aborted", "AbortError")) }
    const timer = setTimeout(() => { signal?.removeEventListener("abort", onAbort); resolve() }, 1000)
    signal?.addEventListener("abort", onAbort, { once: true })
    if (signal?.aborted) onAbort()
  })
}

// Snapshots contain the full preview. Reconnecting replaces it instead of appending replayed text.
export async function subscribeAIRun<T>(sessionId: string, runId: string, options: {
  signal?: AbortSignal
  onSnapshot?: SnapshotListener
} = {}): Promise<T> {
  let lastRevision = -1
  while (true) {
    options.signal?.throwIfAborted()
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
    try {
      const token = getAuthToken()
      const response = await fetch(`/api/sessions/${sessionId}/ai-runs/${runId}/stream`, {
        headers: { Accept: "text/event-stream", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        signal: options.signal,
      })
      if (!response.ok) {
        const body = await response.json() as { detail?: string | { message?: string; code?: string } }
        const detail = body.detail
        throw new AIStreamError(typeof detail === "string" ? detail : detail?.message ?? `HTTP ${response.status}`, response.status, typeof detail === "object" ? detail.code : undefined)
      }
      if (!response.body) throw new AIStreamError("浏览器无法读取流式回复", 500)
      reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let boundary: RegExpExecArray | null
        while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
          const event = buffer.slice(0, boundary.index)
          buffer = buffer.slice(boundary.index + boundary[0].length)
          const lines = event.split(/\r?\n/)
          if (!lines.some((line) => line === "event: snapshot" || line === "event:snapshot")) continue
          const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n")
          let snapshot: AIRunSnapshot<T>
          try { snapshot = JSON.parse(data) as AIRunSnapshot<T> }
          catch { throw new AIStreamError("流式回复格式异常，请重新打开会话", 500, "INVALID_AI_STREAM") }
          if (snapshot.runId !== runId || snapshot.revision <= lastRevision) continue
          lastRevision = snapshot.revision
          options.onSnapshot?.(snapshot)
          listeners.get(`${sessionId}:${runId}`)?.forEach((listener) => listener(snapshot))
          if (snapshot.status === "SUCCEEDED") return snapshot.result as T
          if (snapshot.status === "FAILED" || snapshot.status === "CANCELLED") {
            throw new AIStreamError(snapshot.error?.message ?? (snapshot.status === "CANCELLED" ? "本次生成已中断" : "AI 生成失败"), snapshot.error?.status ?? 503, snapshot.error?.code ?? (snapshot.status === "CANCELLED" ? "AI_RUN_CANCELLED" : "AI_SERVICE_UNAVAILABLE"))
          }
        }
      }
    } catch (error) {
      if (options.signal?.aborted) throw options.signal.reason ?? error
      if (error instanceof AIStreamError) throw error
      if (!(error instanceof TypeError)) throw error
      // A dropped connection only detaches this subscriber; the server task continues.
    } finally {
      await reader?.cancel().catch(() => undefined)
      reader?.releaseLock()
    }
    await reconnectDelay(options.signal)
  }
}
