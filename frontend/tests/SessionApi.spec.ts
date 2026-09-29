import { afterEach, describe, expect, it, vi } from "vitest"

import {
  requestSessionApi,
  SessionApiError,
  submitMasteryCheckAnswers,
} from "../src/api/sessions"
import {
  activateStep,
  fetchSessionSteps,
  saveStepAndGoNext,
  submitStepAttempt,
} from "../src/api/session-steps"

describe("session API errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("posts mastery check answers with the session version", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 12 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
    vi.stubGlobal("fetch", fetchMock)

    await submitMasteryCheckAnswers(
      "12",
      [{ questionId: "mc1", answer: "依据是合并两个 1。" }],
      9,
    )

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/12/mastery-check-answers",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          answers: [{ questionId: "mc1", answer: "依据是合并两个 1。" }],
          version: 9,
        }),
      }),
    )
  })

  it("fetches the current session steps by default", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ steps: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
    vi.stubGlobal("fetch", fetchMock)

    await fetchSessionSteps("12")

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/12/steps?round=current",
      expect.any(Object),
    )
  })

  it("saves a step and advances with the current version", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ steps: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
    vi.stubGlobal("fetch", fetchMock)

    await saveStepAndGoNext("12", 101, "先列出已知条件", 13)

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/12/steps/101/next",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          stepContent: "先列出已知条件",
          version: 13,
        }),
      }),
    )
  })

  it("activates a target step after saving the current step", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ steps: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
    vi.stubGlobal("fetch", fetchMock)

    await activateStep("12", 101, 103, "修改后的当前步骤", 15)

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/12/steps/101/activate",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          currentStepId: 103,
          currentStepContent: "修改后的当前步骤",
          version: 15,
        }),
      }),
    )
  })

  it("submits the current step draft as a step attempt", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 12 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
    vi.stubGlobal("fetch", fetchMock)

    await submitStepAttempt("12", 104, "完成最后一步", 16)

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/12/step-attempts",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          currentStepId: 104,
          currentStepContent: "完成最后一步",
          version: 16,
        }),
      }),
    )
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
