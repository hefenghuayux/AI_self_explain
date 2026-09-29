import type { Session } from "../types/session"
import type {
  StepActivateInput,
  StepAttemptInput,
  StepNextInput,
  StepRound,
  StepsResponse,
} from "../types/session-step"
import { requestSessionApi } from "./sessions"

export function fetchSessionSteps(
  sessionId: string,
  round: StepRound = "current",
): Promise<StepsResponse> {
  return requestSessionApi<StepsResponse>(
    `/api/sessions/${sessionId}/steps?round=${round}`,
  )
}

export function saveStepAndGoNext(
  sessionId: string,
  stepId: number,
  stepContent: string,
  version: number,
): Promise<StepsResponse> {
  const input: StepNextInput = { stepContent, version }
  return requestSessionApi<StepsResponse>(`/api/sessions/${sessionId}/steps/${stepId}/next`, {
    method: "POST",
    body: JSON.stringify(input),
  })
}

export function activateStep(
  sessionId: string,
  targetStepId: number,
  currentStepId: number,
  currentStepContent: string,
  version: number,
): Promise<StepsResponse> {
  const input: StepActivateInput = { currentStepId, currentStepContent, version }
  return requestSessionApi<StepsResponse>(
    `/api/sessions/${sessionId}/steps/${targetStepId}/activate`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  )
}

export function submitStepAttempt(
  sessionId: string,
  currentStepId: number,
  currentStepContent: string,
  version: number,
): Promise<Session> {
  const input: StepAttemptInput = { currentStepId, currentStepContent, version }
  return requestSessionApi<Session>(`/api/sessions/${sessionId}/step-attempts`, {
    method: "POST",
    body: JSON.stringify(input),
  })
}
