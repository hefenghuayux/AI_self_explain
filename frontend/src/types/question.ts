export interface QuestionInput {
  questionContent: string
  standardAnswer: string | null
  rubricPoints: string[] | null
  commonErrors: string[] | null
  alternativeSolutions: string[] | null
  layeredHints: string[] | null
  guidedQuestions: string[] | null
  fullSolution: string | null
}

export interface Question extends QuestionInput {
  id: number
  evaluationMode: "FULL_RUBRIC" | "BASIC" | "AI_GENERAL"
  archivedAt: string | null
  createdAt: string
  updatedAt: string
}

export interface QuestionListItem {
  id: number
  questionContent: string
  gradePeriod: number | null
  subject: string | null
  qType: number | null
  difficultyLevel: number | null
  evaluationMode: "FULL_RUBRIC" | "BASIC" | "AI_GENERAL"
  rubricPointCount: number
  archivedAt: string | null
}

export interface QuestionPagination {
  page: number
  pageSize: number
  total: number
  totalPages: number
}

export interface QuestionListResponse {
  items: QuestionListItem[]
  pagination: QuestionPagination
}

export interface QuestionFilterOptions {
  gradePeriods: number[]
  subjects: string[]
}

export interface QuestionListQuery {
  page: number
  pageSize: number
  includeArchived: boolean
  gradePeriod?: number
  subject?: string
  keyword?: string
}

export interface QuestionFormInput {
  questionContent: string
  standardAnswer: string
  rubricPoints: string[]
  commonErrors: string[]
  alternativeSolutions: string[]
  layeredHints: string[]
  guidedQuestions: string[]
  fullSolution: string
}

export function createQuestionDraft(): QuestionFormInput {
  return {
    questionContent: "",
    standardAnswer: "",
    rubricPoints: [],
    commonErrors: [],
    alternativeSolutions: [],
    layeredHints: [],
    guidedQuestions: [],
    fullSolution: "",
  }
}

export function toQuestionFormInput(question: Question): QuestionFormInput {
  return {
    questionContent: question.questionContent,
    standardAnswer: question.standardAnswer ?? "",
    rubricPoints: [...(question.rubricPoints ?? [])],
    commonErrors: [...(question.commonErrors ?? [])],
    alternativeSolutions: [...(question.alternativeSolutions ?? [])],
    layeredHints: [...(question.layeredHints ?? [])],
    guidedQuestions: [...(question.guidedQuestions ?? [])],
    fullSolution: question.fullSolution ?? "",
  }
}
