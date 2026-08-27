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
})
