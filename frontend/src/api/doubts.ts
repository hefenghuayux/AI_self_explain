import { requestSessionApi } from "./sessions"

export interface IndependentDoubt {
  runId: string
  status: "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED"
  question: string
  result: { content: string } | null
  error: { message: string; code: string; status: number } | null
}

export function fetchIndependentDoubts(sessionId: string): Promise<IndependentDoubt[]> {
  return requestSessionApi<IndependentDoubt[]>(`/api/sessions/${sessionId}/independent-doubts`)
}

export function startIndependentDoubt(sessionId: string, runId: string, doubtText: string, mainDraft: string): Promise<{ runId: string }> {
  return requestSessionApi<{ runId: string }>(`/api/sessions/${sessionId}/ai-runs`, {
    method: "POST",
    body: JSON.stringify({ runId, operation: "independent-doubt", input: { doubtText, mainDraft } }),
  })
}
