import type {
  GuidedAnswer,
  InitialChoice,
  LearningTimelineItem,
  Session,
  SessionHistoryItem,
} from "../types/session"
import { getAuthToken } from "../stores/auth"
import { teacherSpeechAutoPlay } from "../stores/teacherSpeech"
import { AIStreamError, subscribeAIRun } from "./ai-stream"

interface SessionApiErrorDetail {
  code?: string
  message?: string
  sessionId?: number
}

export class SessionApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly sessionId?: number,
  ) {
    super(message)
    this.name = "SessionApiError"
  }
}

export async function requestSessionApi<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers({
    "Content-Type": "application/json",
    ...(getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {}),
  })
  new Headers(options?.headers).forEach((value, key) => headers.set(key, value))
  if (options?.method?.toUpperCase() === "POST"
    && /^\/api\/sessions\/[^/]+\/(text-attempts|step-attempts|graded-step-attempts|request-support|ask-doubt|guided-answers|full-solution-understanding|mastery-check-answers)$/.test(path)) {
    headers.set("X-Teacher-Speech-Prewarm", String(teacherSpeechAutoPlay.value))
  }
  const streamOperation = /^\/api\/sessions\/([^/]+)\/(text-attempts|step-attempts|graded-step-attempts|request-support|ask-doubt|guided-answers|appeal|full-solution-understanding|mastery-check-answers|grading\/retry)$/.exec(path)
  const runId = headers.get("X-AI-Run-ID")
  const streaming = options?.method?.toUpperCase() === "POST" && streamOperation && runId
  const response = await fetch(streaming ? `/api/sessions/${streamOperation[1]}/ai-runs` : path, {
    ...options,
    // Starting the background task must survive detaching the page's stream reader.
    ...(streaming ? { signal: undefined, body: JSON.stringify({ runId, operation: streamOperation[2], input: options?.body ? JSON.parse(String(options.body)) : {} }) } : {}),
    headers,
  })
  if (!response.ok) {
    const responseBody = (await response.json()) as {
      detail?: string | Array<{ msg: string }> | SessionApiErrorDetail
    }
    let detailMessage: string
    let detailCode: string | undefined
    let detailSessionId: number | undefined
    if (Array.isArray(responseBody.detail)) {
      detailMessage = responseBody.detail.map((item) => item.msg).join("；")
    } else if (typeof responseBody.detail === "string") {
      detailMessage = responseBody.detail
    } else if (responseBody.detail && typeof responseBody.detail === "object") {
      detailMessage = responseBody.detail.message ?? `HTTP ${response.status}`
      detailCode = responseBody.detail.code
      detailSessionId = responseBody.detail.sessionId
    } else {
      detailMessage = `HTTP ${response.status}`
    }
    throw new SessionApiError(
      `会话操作失败：${detailMessage}`,
      response.status,
      detailCode,
      detailSessionId,
    )
  }
  if (streaming) {
    await response.json()
    try { return await subscribeAIRun<T>(streamOperation[1], runId, { signal: options?.signal ?? undefined }) }
    catch (error) {
      if (error instanceof AIStreamError) throw new SessionApiError(error.message, error.status, error.code, Number(streamOperation[1]))
      throw error
    }
  }
  return (await response.json()) as T
}

export function createSession(questionId: string, restart = false): Promise<Session> {
  return requestSessionApi<Session>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ questionId: Number(questionId), restart }),
  })
}

export function fetchSession(sessionId: string): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}`)
}

export function fetchSessionHistory(): Promise<SessionHistoryItem[]> {
  return requestSessionApi<SessionHistoryItem[]>("/api/sessions/history")
}

export function fetchLearningTimeline(sessionId: string): Promise<LearningTimelineItem[]> {
  return requestSessionApi<LearningTimelineItem[]>(`/api/sessions/${sessionId}/timeline`)
}

export function cancelCurrentRun(sessionId: string, runId: string): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/cancel-current-run`, {
    method: "POST",
    body: JSON.stringify({ runId }),
  })
}

export function submitInitialChoice(
  sessionId: string,
  choice: InitialChoice,
  version: number,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/initial-choice`, {
    method: "POST",
    body: JSON.stringify({ choice, version }),
  })
}

export function submitTextAttempt(
  sessionId: string,
  confirmedText: string,
  version: number,
  voiceAttemptId?: number,
  runId?: string,
  signal?: AbortSignal,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/text-attempts`, {
    method: "POST",
    body: JSON.stringify({ confirmedText, version, voiceAttemptId }),
    headers: runId ? { "X-AI-Run-ID": runId } : undefined,
    signal,
  })
}

export function continueExplaining(sessionId: string, version: number): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/continue`, {
    method: "POST",
    body: JSON.stringify({ version }),
  })
}

export function requestSupport(sessionId: string, mainDraft: string, version: number, runId?: string, signal?: AbortSignal): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/request-support`, {
    method: "POST",
    body: JSON.stringify({ mainDraft, version }),
    headers: runId ? { "X-AI-Run-ID": runId } : undefined,
    signal,
  })
}

export function askDoubt(
  sessionId: string,
  mainDraft: string,
  doubtText: string,
  version: number,
  voiceAttemptId?: number,
  runId?: string,
  signal?: AbortSignal,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/ask-doubt`, {
    method: "POST",
    body: JSON.stringify({ mainDraft, doubtText, version, voiceAttemptId }),
    headers: runId ? { "X-AI-Run-ID": runId } : undefined,
    signal,
  })
}

export function submitGuidedAnswers(
  sessionId: string,
  answers: GuidedAnswer[],
  version: number,
  voiceAttemptId?: number,
  runId?: string,
  signal?: AbortSignal,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/guided-answers`, {
    method: "POST",
    body: JSON.stringify({ answers, version, voiceAttemptId }),
    headers: runId ? { "X-AI-Run-ID": runId } : undefined,
    signal,
  })
}

export function submitAppeal(
  sessionId: string,
  reason: string,
  version: number,
  voiceAttemptId?: number,
  runId?: string,
  signal?: AbortSignal,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/appeal`, {
    method: "POST",
    body: JSON.stringify({ reason, version, voiceAttemptId }),
    headers: runId ? { "X-AI-Run-ID": runId } : undefined,
    signal,
  })
}

export function submitSolutionUnderstanding(
  sessionId: string,
  understood: boolean,
  version: number,
  runId?: string,
  signal?: AbortSignal,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/full-solution-understanding`, {
    method: "POST",
    body: JSON.stringify({ understood, version }),
    headers: runId ? { "X-AI-Run-ID": runId } : undefined,
    signal,
  })
}

export function submitMasteryCheckAnswers(
  sessionId: string,
  answers: GuidedAnswer[],
  version: number,
  runId?: string,
  signal?: AbortSignal,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/mastery-check-answers`, {
    method: "POST",
    body: JSON.stringify({ answers, version }),
    headers: runId ? { "X-AI-Run-ID": runId } : undefined,
    signal,
  })
}
