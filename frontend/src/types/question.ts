export interface QuestionInput {
  questionContent: string
  standardAnswer: string
  rubricPoints: string[]
  commonErrors: string[]
  alternativeSolutions: string[]
  layeredHints: string[]
  fullSolution: string
}

export interface Question extends QuestionInput {
  id: number
  archivedAt: string | null
  createdAt: string
  updatedAt: string
}

export function createQuestionDraft(): QuestionInput {
  return {
    questionContent: "",
    standardAnswer: "",
    rubricPoints: [""],
    commonErrors: [""],
    alternativeSolutions: [""],
    layeredHints: [""],
    fullSolution: "",
  }
}

export function toQuestionInput(question: Question): QuestionInput {
  return {
    questionContent: question.questionContent,
    standardAnswer: question.standardAnswer,
    rubricPoints: [...question.rubricPoints],
    commonErrors: [...question.commonErrors],
    alternativeSolutions: [...question.alternativeSolutions],
    layeredHints: [...question.layeredHints],
    fullSolution: question.fullSolution,
  }
}
