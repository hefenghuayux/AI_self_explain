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

export interface SupportEvent {
  id: number
  supportType: "GIVE_HINT" | "GIVE_CORRECTION" | "CORRECT_AND_ASK"
  round: number
  status: "VALID"
  content: string
  createdAt: string
}

export interface LearningTimelineItem {
  id: string
  eventType: "EVALUATION" | "SUPPORT" | "FULL_SOLUTION" | "NEED_HUMAN"
  content: string
  correctness: AIEvaluation["correctness"] | null
  completeness: AIEvaluation["completeness"] | null
  action: AIEvaluation["nextAction"] | SupportEvent["supportType"] | null
  createdAt: string
}

export interface Session {
  id: number
  questionId: number
  status: SessionStatus
  flowStage: FlowStage
  round: number
  supportCountRound: number
  supportCountTotal: number
  noProgressCount: number
  solutionExposed: boolean
  completionType: "INDEPENDENT" | "WITH_SUPPORT" | "AFTER_SOLUTION" | null
  coveredPointsCurrentRound: string[]
  coveredPointsAll: string[]
  version: number
  initialChoice: InitialChoice | null
  needHumanReason: string | null
  latestEvaluation: AIEvaluation | null
  latestSupport: SupportEvent | null
}
