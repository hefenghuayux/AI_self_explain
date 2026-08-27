import DOMPurify from "dompurify"
import renderMathInElement from "katex/contrib/auto-render"

export function sanitizeQuestionHtml(html: string): string {
  const container = document.createElement("div")
  container.innerHTML = DOMPurify.sanitize(html)

  renderMathInElement(container, {
    delimiters: [
      { left: "$$", right: "$$", display: true },
      { left: "\\\\[", right: "\\\\]", display: true },
      { left: "$", right: "$", display: false },
      { left: "\\\\(", right: "\\\\)", display: false },
    ],
    throwOnError: false,
  })

  return DOMPurify.sanitize(container.innerHTML)
}
