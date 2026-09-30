import DOMPurify from "dompurify"
import katex from "katex"

const inlineMath = /\\\(([\s\S]*?)\\\)/g

export function renderStudentTextHtml(text: string): string {
  const container = document.createElement("div")
  let textStart = 0

  for (const match of text.matchAll(inlineMath)) {
    const matchStart = match.index
    container.append(document.createTextNode(text.slice(textStart, matchStart)))

    const formula = document.createElement("span")
    try {
      if (!match[1].trim()) throw new Error("empty formula")
      katex.render(match[1], formula, { throwOnError: true, trust: false })
    } catch {
      formula.className = "student-math-error"
      formula.title = "公式无法解析，已显示原文"
      formula.textContent = match[0]
    }
    container.append(formula)
    textStart = matchStart + match[0].length
  }

  container.append(document.createTextNode(text.slice(textStart)))
  return DOMPurify.sanitize(container.innerHTML)
}
