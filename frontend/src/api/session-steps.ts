import type { Session } from "../types/session"
import type { StepAttemptInput, StepRound, StepsResponse } from "../types/session-step"
import { requestSessionApi } from "./sessions"

export function fetchSessionSteps(
  sessionId: string,
  round: StepRound = "current",
): Promise<StepsResponse> {
  return requestSessionApi<StepsResponse>(
    `/api/sessions/${sessionId}/steps?round=${round}`,
  )
}

export function submitStepAttempt(
  sessionId: string,
  currentStepContent: string,
  version: number,
): Promise<Session> {
  const input: StepAttemptInput = { currentStepContent, version }
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/step-attempts`, {
    method: "POST",
    body: JSON.stringify(input),
  })
}
