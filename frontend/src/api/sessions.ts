import type { GuidedAnswer, InitialChoice, LearningTimelineItem, Session } from "../types/session"
import { getAuthToken } from "../stores/auth"

async function requestSessionApi<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {}),
    },
    ...options,
  })
  if (!response.ok) {
    const responseBody = (await response.json()) as { detail?: string | Array<{ msg: string }> }
    const detail = Array.isArray(responseBody.detail)
      ? responseBody.detail.map((item) => item.msg).join("；")
      : responseBody.detail
    throw new Error(`会话操作失败：${detail ?? `HTTP ${response.status}`}`)
  }
  return (await response.json()) as T
}

export function createSession(questionId: string): Promise<Session> {
  return requestSessionApi<Session>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ questionId: Number(questionId) }),
  })
}

export function fetchSession(sessionId: string): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}`)
}

export function fetchLearningTimeline(sessionId: string): Promise<LearningTimelineItem[]> {
  return requestSessionApi<LearningTimelineItem[]>(`/api/sessions/${sessionId}/timeline`)
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
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/text-attempts`, {
    method: "POST",
    body: JSON.stringify({ confirmedText, version }),
  })
}

export function confirmVoiceAttempt(
  sessionId: string,
  attemptId: number,
  confirmedText: string,
  version: number,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/voice-attempts/confirm`, {
    method: "POST",
    body: JSON.stringify({ attemptId, confirmedText, version }),
  })
}

export function retryEvaluation(sessionId: string, version: number): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/evaluate`, {
    method: "POST",
    body: JSON.stringify({ version }),
  })
}

export function continueExplaining(sessionId: string, version: number): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/continue`, {
    method: "POST",
    body: JSON.stringify({ version }),
  })
}

export function requestSupport(sessionId: string, mainDraft: string, version: number): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/request-support`, {
    method: "POST",
    body: JSON.stringify({ mainDraft, version }),
  })
}

export function askDoubt(
  sessionId: string,
  mainDraft: string,
  doubtText: string,
  version: number,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/ask-doubt`, {
    method: "POST",
    body: JSON.stringify({ mainDraft, doubtText, version }),
  })
}

export function submitGuidedAnswers(
  sessionId: string,
  answers: GuidedAnswer[],
  version: number,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/guided-answers`, {
    method: "POST",
    body: JSON.stringify({ answers, version }),
  })
}

export function submitAppeal(sessionId: string, reason: string, version: number): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/appeal`, {
    method: "POST",
    body: JSON.stringify({ reason, version }),
  })
}

export function submitSolutionUnderstanding(
  sessionId: string,
  understood: boolean,
  version: number,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/full-solution-understanding`, {
    method: "POST",
    body: JSON.stringify({ understood, version }),
  })
}
