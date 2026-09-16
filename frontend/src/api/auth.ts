import type { AuthResponse, User } from "../types/auth"

/** 尝试解析后端错误体 JSON；非 JSON（如纯文本 500 Internal Server Error）时回退到 HTTP 状态文案 */
async function parseErrorDetail(response: Response, fallbackPrefix: string): Promise<string> {
  const fallback = `${fallbackPrefix}：HTTP ${response.status}`
  const text = await response.text()
  if (!text) return fallback
  try {
    const body = JSON.parse(text) as { detail?: string | Array<{ msg: string }> }
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => item.msg).join("；")
      : body.detail
    return detail ?? fallback
  } catch {
    return fallback
  }
}

export async function login(username: string, password: string, rememberLogin: boolean): Promise<AuthResponse> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, rememberLogin }),
  })
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response, "登录失败"))
  }
  return (await response.json()) as AuthResponse
}

export async function register(username: string, password: string, fullName: string): Promise<User> {
  const response = await fetch("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, fullName }),
  })
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response, "注册失败"))
  }
  return (await response.json()) as User
}

export async function fetchCurrentUser(token: string): Promise<User> {
  const response = await fetch("/api/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) throw new Error("登录状态已失效")
  return (await response.json()) as User
}

export async function logout(token: string): Promise<void> {
  const response = await fetch("/api/auth/logout", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok && response.status !== 401) {
    throw new Error(`退出登录失败：HTTP ${response.status}`)
  }
}
