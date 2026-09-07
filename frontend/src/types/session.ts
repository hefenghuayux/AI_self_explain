export type InitialChoice = "KNOW" | "NOT_KNOW" | "HAS_QUESTION"
export type VoiceInputTarget = "SELF_EXPLANATION" | "GUIDED_ANSWER" | "DOUBT" | "APPEAL"

export type SessionStatus = "IN_PROGRESS" | "COMPLETED" | "STOPPED_LIMIT" | "NEED_HUMAN" | "PAUSED"

export type FlowStage =
  | "WAIT_INITIAL_CHOICE"
  | "CAPTURING_INPUT"
  | "TRANSCRIBING"
  | "AI_EVALUATING"
  | "WAIT_STUDENT_ACTION"
  | "WAIT_GUIDED_ANSWERS"
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
  coveredPoints: number[]
  errorEvidence: ErrorEvidence[]
  needHumanReason: string | null
  promptVersion: string
  modelProvider: string
  modelName: string
  createdAt: string
}

export interface SupportEvent {
  id: number
  supportType: "ASK_FOCUSED_QUESTION" | "GIVE_HINT" | "GIVE_CORRECTION" | "CORRECT_AND_ASK"
  round: number
  status: "VALID" | "REFUSED"
  content: string
  supportKind: "EVALUATION" | "GUIDED_QUESTIONS" | "SIMPLE_DOUBT" | "CURRENT_STEP"
  mainDraft: string | null
  doubtText: string | null
  guidedQuestions: GuidedQuestion[] | null
  guidedAnswers: GuidedAnswer[] | null
  followUpContent: string | null
  createdAt: string
}

export interface GuidedQuestion {
  id: string
  question: string
}

export interface GuidedAnswer {
  questionId: string
  answer: string
}

export interface LearningTimelineItem {
  id: string
  eventType: "SUBMISSION" | "EVALUATION" | "SUPPORT" | "FULL_SOLUTION" | "NEED_HUMAN"
  speaker: "STUDENT" | "AI" | "SYSTEM"
  submissionType: "SELF_EXPLANATION" | "SUPPORT_REQUEST" | "GUIDED_ANSWER" | "DOUBT" | "APPEAL" | null
  content: string
  correctness: AIEvaluation["correctness"] | null
  completeness: AIEvaluation["completeness"] | null
  action: "COMPLETE" | "NEED_HUMAN" | SupportEvent["supportType"] | null
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
  noProgressHelpRequestCount: number
  solutionExposed: boolean
  completionType: "INDEPENDENT" | "WITH_SUPPORT" | "AFTER_SOLUTION" | null
  coveredPointsCurrentRound: string[]
  coveredPointsAll: string[]
  currentDraft: string
  version: number
  initialChoice: InitialChoice | null
  needHumanReason: string | null
  latestEvaluation: AIEvaluation | null
  latestSupport: SupportEvent | null
  teachingGeneration:
    | { status: "NOT_REQUIRED" }
    | { status: "SUCCEEDED"; supportEventId: number }
    | null
}
