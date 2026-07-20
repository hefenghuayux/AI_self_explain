import type { InitialChoice, Session } from "../types/session"

async function requestSessionApi<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
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
