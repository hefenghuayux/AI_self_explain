import type {
  Question,
  QuestionFilterOptions,
  QuestionInput,
  QuestionListQuery,
  QuestionListResponse,
} from "../types/question"
import { getAuthToken } from "../stores/auth"

async function requestQuestionApi<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {}),
    },
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

export function fetchQuestions(query: QuestionListQuery): Promise<QuestionListResponse> {
  const parameters = new URLSearchParams({
    page: String(query.page),
    page_size: String(query.pageSize),
  })
  if (query.includeArchived) parameters.set("include_archived", "true")
  if (query.gradePeriod !== undefined) parameters.set("grade_period", String(query.gradePeriod))
  if (query.subject) parameters.set("subject", query.subject)
  if (query.keyword) parameters.set("keyword", query.keyword)
  return requestQuestionApi<QuestionListResponse>(`/api/questions?${parameters}`)
}

export function fetchQuestionFilterOptions(includeArchived: boolean): Promise<QuestionFilterOptions> {
  const query = includeArchived ? "?include_archived=true" : ""
  return requestQuestionApi<QuestionFilterOptions>(`/api/questions/filter-options${query}`)
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
