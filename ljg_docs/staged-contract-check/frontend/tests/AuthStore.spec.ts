import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

beforeEach(() => {
  localStorage.clear()
  vi.resetModules()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("auth store", () => {
  it("persists the token only when remember login is selected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          token: "remembered-token",
          expiresAt: "2026-08-22T00:00:00Z",
          user: { id: 1, username: "student", fullName: "学生", role: "STUDENT" },
        }),
      }),
    )
    const auth = await import("../src/stores/auth")

    await auth.login("student", "secret6", true)

    expect(localStorage.getItem("ai-self-explain-auth-token")).toBe("remembered-token")
    expect(auth.authUser.value?.role).toBe("STUDENT")
  })

  it("keeps an unremembered login out of persistent storage", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          token: "memory-token",
          expiresAt: "2026-08-22T00:00:00Z",
          user: { id: 2, username: "teacher", fullName: "教师", role: "TEACHER" },
        }),
      }),
    )
    const auth = await import("../src/stores/auth")

    await auth.login("teacher", "secret6", false)

    expect(localStorage.getItem("ai-self-explain-auth-token")).toBeNull()
    expect(auth.getAuthToken()).toBe("memory-token")
    expect(await auth.initializeAuth()).toBe(true)
  })

  it("clears the remembered token after logout", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          token: "logout-token",
          expiresAt: "2026-08-22T00:00:00Z",
          user: { id: 3, username: "student", fullName: "学生", role: "STUDENT" },
        }),
      })
      .mockResolvedValueOnce({ ok: true, status: 204 })
    vi.stubGlobal("fetch", fetchMock)
    const auth = await import("../src/stores/auth")
    await auth.login("student", "secret6", true)

    await auth.logout()

    expect(localStorage.getItem("ai-self-explain-auth-token")).toBeNull()
    expect(auth.getAuthToken()).toBeUndefined()
  })
})
