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

export interface Session {
  id: number
  questionId: number
  status: SessionStatus
  flowStage: FlowStage
  round: number
  version: number
  initialChoice: InitialChoice | null
}
