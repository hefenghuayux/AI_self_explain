import { afterEach, describe, expect, it, vi } from "vitest"

import { login, register } from "../src/api/auth"

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("auth api error handling", () => {
  it("login falls back to HTTP message when the error body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        text: async () => "Internal Server Error",
      }),
    )

    await expect(login("student", "secret6", false)).rejects.toThrow("登录失败：HTTP 500")
  })

  it("login surfaces backend detail for a JSON error body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        text: async () => JSON.stringify({ detail: "用户名或密码错误" }),
      }),
    )

    await expect(login("student", "wrongpass", false)).rejects.toThrow("用户名或密码错误")
  })

  it("register joins array detail messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        text: async () =>
          JSON.stringify({ detail: [{ msg: "密码至少 6 位" }, { msg: "用户名不能为空" }] }),
      }),
    )

    await expect(register("", "short", "学生")).rejects.toThrow("密码至少 6 位；用户名不能为空")
  })

  it("register falls back when the error body is empty", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 503, text: async () => "" }),
    )

    await expect(register("student", "secret6", "学生")).rejects.toThrow("注册失败：HTTP 503")
  })
})
