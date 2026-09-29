export type StepRound = number | "current"
export type StepStatus = "DRAFT" | "SAVED" | "SUBMITTED"

export interface StepResponse {
  id: number
  seq: number
  stepContent: string | null
  explainTranscript: string | null
  status: StepStatus
  updatedAt: string
}

export interface StepsResponse {
  round: number
  draftId: string
  currentStepId: number | null
  version: number
  steps: StepResponse[]
}

export interface StepNextInput {
  stepContent: string
  version: number
}

export interface StepActivateInput {
  currentStepId: number
  currentStepContent: string
  version: number
}

export interface StepAttemptInput {
  currentStepId: number
  currentStepContent: string
  version: number
}
