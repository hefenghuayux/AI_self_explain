import type { AuthResponse, User } from "../types/auth"

export async function login(username: string, password: string, rememberLogin: boolean): Promise<AuthResponse> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, rememberLogin }),
  })
  if (!response.ok) {
    const body = (await response.json()) as { detail?: string }
    throw new Error(body.detail ?? `登录失败：HTTP ${response.status}`)
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
    const body = (await response.json()) as { detail?: string | Array<{ msg: string }> }
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => item.msg).join("；")
      : body.detail
    throw new Error(detail ?? `注册失败：HTTP ${response.status}`)
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
