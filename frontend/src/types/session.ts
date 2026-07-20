export type InitialChoice = "KNOW" | "NOT_KNOW"

export type SessionStatus = "IN_PROGRESS" | "COMPLETED" | "STOPPED_LIMIT" | "NEED_HUMAN" | "PAUSED"

export type FlowStage =
  | "WAIT_INITIAL_CHOICE"
  | "CAPTURING_INPUT"
  | "CONFIRMING_TEXT"
  | "TRANSCRIBING"
  | "AI_EVALUATING"
  | "WAIT_STUDENT_ACTION"
  | "SHOWING_FULL_SOLUTION"

export interface ErrorEvidence {
  quote: string
  locationDescription: string
  reason: string
  thinkingDirection: string
}

export interface AIEvaluation {
  id: number
  correctness: "CORRECT" | "WRONG" | "UNCERTAIN"
  completeness: "COMPLETE" | "INCOMPLETE"
  coveredPoints: string[]
  missingPoints: string[]
  errorEvidence: ErrorEvidence[]
  feedback: string
  confidence: number
  nextAction:
    | "COMPLETE"
    | "ASK_FOCUSED_QUESTION"
    | "GIVE_CORRECTION"
    | "CORRECT_AND_ASK"
    | "GIVE_HINT"
    | "NEED_HUMAN"
  needHumanReason: string | null
  promptVersion: string
  modelProvider: string
  modelName: string
  createdAt: string
}

export interface Session {
  id: number
  questionId: number
  status: SessionStatus
  flowStage: FlowStage
  round: number
  version: number
  initialChoice: InitialChoice | null
  needHumanReason: string | null
  latestEvaluation: AIEvaluation | null
}
