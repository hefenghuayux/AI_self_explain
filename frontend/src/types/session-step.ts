export type StepRound = number | "current"

export interface StepResponse {
  id: number
  stepContent: string | null
  explainTranscript: string | null
  updatedAt: string
}

export interface StepsResponse {
  round: number
  currentStepId: number | null
  version: number
  step: StepResponse | null
}

export interface StepAttemptInput {
  currentStepContent: string
  version: number
}
