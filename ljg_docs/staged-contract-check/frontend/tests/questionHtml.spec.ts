import { describe, expect, it } from "vitest"

import { sanitizeQuestionHtml } from "../src/utils/questionHtml"

describe("sanitizeQuestionHtml", () => {
  it("preserves question text and images while removing executable markup", () => {
    const html = '<p style="text-align:justify">题干</p><img src="https://example.test/question.png" onerror="alert(1)"><script>alert(1)</script>'

    const result = sanitizeQuestionHtml(html)

    expect(result).toContain('style="text-align:justify"')
    expect(result).toContain('<img src="https://example.test/question.png">')
    expect(result).not.toContain("onerror")
    expect(result).not.toContain("script")
  })

  it("renders inline LaTeX mathematics in imported question HTML", () => {
    const result = sanitizeQuestionHtml('<p>$AB=10\\mathrm{cm}$，$\\angle AOE=90^{\\circ}$</p>')
    const document = new DOMParser().parseFromString(result, "text/html")

    expect(document.querySelectorAll(".katex")).toHaveLength(2)
    expect(document.querySelector(".katex")?.textContent).toContain("AB=10cm")
    expect(document.querySelectorAll(".katex")[1]?.textContent).toContain("∠AOE=90∘")
  })
})
