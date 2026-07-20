import type { Question, QuestionInput } from "../types/question"

async function requestQuestionApi<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  })
  if (!response.ok) {
    const responseBody = (await response.json()) as { detail?: string | Array<{ msg: string }> }
    const detail = Array.isArray(responseBody.detail)
      ? responseBody.detail.map((item) => item.msg).join("；")
      : responseBody.detail
    throw new Error(`题目保存失败：${detail ?? `HTTP ${response.status}`}`)
  }
  return (await response.json()) as T
}

export function fetchQuestions(includeArchived = false): Promise<Question[]> {
  const query = includeArchived ? "?include_archived=true" : ""
  return requestQuestionApi<Question[]>(`/api/questions${query}`)
}

export function fetchQuestion(questionId: string): Promise<Question> {
  return requestQuestionApi<Question>(`/api/questions/${questionId}`)
}

export function createQuestion(question: QuestionInput): Promise<Question> {
  return requestQuestionApi<Question>("/api/questions", {
    method: "POST",
    body: JSON.stringify(question),
  })
}

export function updateQuestion(questionId: string, question: QuestionInput): Promise<Question> {
  return requestQuestionApi<Question>(`/api/questions/${questionId}`, {
    method: "PUT",
    body: JSON.stringify(question),
  })
}

export function archiveQuestion(questionId: string): Promise<Question> {
  return requestQuestionApi<Question>(`/api/questions/${questionId}/archive`, { method: "POST" })
}

export function restoreQuestion(questionId: string): Promise<Question> {
  return requestQuestionApi<Question>(`/api/questions/${questionId}/restore`, { method: "POST" })
}
