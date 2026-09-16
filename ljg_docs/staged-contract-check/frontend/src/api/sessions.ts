import type { GuidedAnswer, InitialChoice, LearningTimelineItem, Session } from "../types/session"
import { getAuthToken } from "../stores/auth"

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
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {}),
    },
    ...options,
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
  voiceAttemptId?: number,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/text-attempts`, {
    method: "POST",
    body: JSON.stringify({ confirmedText, version, voiceAttemptId }),
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
  voiceAttemptId?: number,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/ask-doubt`, {
    method: "POST",
    body: JSON.stringify({ mainDraft, doubtText, version, voiceAttemptId }),
  })
}

export function submitGuidedAnswers(
  sessionId: string,
  answers: GuidedAnswer[],
  version: number,
  voiceAttemptId?: number,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/guided-answers`, {
    method: "POST",
    body: JSON.stringify({ answers, version, voiceAttemptId }),
  })
}

export function submitAppeal(
  sessionId: string,
  reason: string,
  version: number,
  voiceAttemptId?: number,
): Promise<Session> {
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/appeal`, {
    method: "POST",
    body: JSON.stringify({ reason, version, voiceAttemptId }),
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
