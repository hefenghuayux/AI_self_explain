import DOMPurify from "dompurify"

export function sanitizeQuestionHtml(html: string): string {
  return DOMPurify.sanitize(html)
}
