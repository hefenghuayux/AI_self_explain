import { afterEach, describe, expect, it, vi } from "vitest"

import { requestSessionApi, SessionApiError } from "../src/api/sessions"

describe("session API errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("preserves structured teaching failure details", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({
        detail: {
          code: "TEACHING_GENERATION_FAILED",
          message: "教学生成失败，会话已进入人工处理",
          sessionId: 12,
        },
      }),
      {
        status: 502,
        headers: { "Content-Type": "application/json" },
      },
    )))

    const error = await requestSessionApi("/api/sessions/12/text-attempts").catch(
      (reason: unknown) => reason,
    )

    expect(error).toBeInstanceOf(SessionApiError)
    expect(error).toMatchObject({
      message: "会话操作失败：教学生成失败，会话已进入人工处理",
      status: 502,
      code: "TEACHING_GENERATION_FAILED",
      sessionId: 12,
    })
  })
})
