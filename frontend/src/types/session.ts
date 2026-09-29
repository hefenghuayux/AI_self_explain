export type InitialChoice = "KNOW" | "NOT_KNOW" | "HAS_QUESTION"
export type VoiceInputTarget =
  | "SELF_EXPLANATION"
  | "SELF_EXPLANATION_STEP"
  | "SELF_EXPLANATION_EXPLAIN"
  | "GUIDED_ANSWER"
  | "DOUBT"
  | "APPEAL"

export type SessionStatus = "IN_PROGRESS" | "COMPLETED" | "STOPPED_LIMIT" | "PAUSED" | "NEEDS_REVIEW"

export type FlowStage =
  | "WAIT_INITIAL_CHOICE"
  | "CAPTURING_INPUT"
  | "TRANSCRIBING"
  | "AI_EVALUATING"
  | "WAIT_STUDENT_ACTION"
  | "WAIT_GUIDED_ANSWERS"
  | "WAIT_MASTERY_CHECK"
  | "SHOWING_FULL_SOLUTION"

export interface AIEvaluation {
  id: number
  correctness: "CORRECT" | "WRONG"
  completeness: "COMPLETE" | "INCOMPLETE"
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

export interface MasteryCheckQuestion {
  id: string
  question: string
}

export interface MasteryCheckResult {
  questionId: string
  passed: boolean
  basis: string
}

export interface MasteryCheck {
  questions: MasteryCheckQuestion[]
  answers: GuidedAnswer[] | null
  results: MasteryCheckResult[] | null
  outcome: "COMPLETED" | "NEEDS_REVIEW" | null
}

export interface LearningTimelineItem {
  id: string
  eventType:
    | "SUBMISSION"
    | "EVALUATION"
    | "SUPPORT"
    | "GUIDED_QUESTIONS"
    | "FOLLOW_UP"
    | "MASTERY_QUESTIONS"
    | "MASTERY_ANSWER"
    | "MASTERY_RESULT"
    | "FULL_SOLUTION"
    | "NEED_HUMAN"
  speaker: "STUDENT" | "AI" | "SYSTEM"
  submissionType:
    | "SELF_EXPLANATION"
    | "SUPPORT_REQUEST"
    | "GUIDED_ANSWER"
    | "DOUBT"
    | "APPEAL"
    | "MASTERY_ANSWER"
    | null
  content: string
  correctness: AIEvaluation["correctness"] | null
  completeness: AIEvaluation["completeness"] | null
  action: "COMPLETE" | SupportEvent["supportType"] | null
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
  completionType: "INDEPENDENT" | "WITH_SUPPORT" | "AFTER_SOLUTION" | "AFTER_MASTERY_CHECK" | null
  currentDraft: string
  currentStepId: number | null
  version: number
  initialChoice: InitialChoice | null
  needHumanReason: string | null
  latestEvaluation: AIEvaluation | null
  latestSupport: SupportEvent | null
  teachingGeneration:
    | { status: "NOT_REQUIRED" }
    | { status: "SUCCEEDED"; supportEventId: number }
    | null
  masteryCheck: MasteryCheck | null
}
