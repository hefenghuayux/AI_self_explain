import { computed, ref } from "vue"

import { fetchCurrentUser, login as loginApi, logout as logoutApi, register as registerApi } from "../api/auth"
import type { User } from "../types/auth"

const STORAGE_KEY = "ai-self-explain-auth-token"
const token = ref<string>()
const currentUser = ref<User>()
let initialized = false

export const authUser = computed(() => currentUser.value)
export const isAuthenticated = computed(() => Boolean(currentUser.value && token.value))

export function getAuthToken(): string | undefined {
  return token.value
}

export async function initializeAuth(): Promise<boolean> {
  if (initialized) return isAuthenticated.value
  initialized = true
  const savedToken = localStorage.getItem(STORAGE_KEY)
  if (!savedToken) return false
  token.value = savedToken
  try {
    currentUser.value = await fetchCurrentUser(savedToken)
    return true
  } catch {
    clearAuth()
    return false
  }
}

export async function login(username: string, password: string, rememberLogin: boolean): Promise<void> {
  const response = await loginApi(username, password, rememberLogin)
  token.value = response.token
  currentUser.value = response.user
  if (rememberLogin) localStorage.setItem(STORAGE_KEY, response.token)
  else localStorage.removeItem(STORAGE_KEY)
}

export async function register(username: string, password: string, fullName: string): Promise<User> {
  return registerApi(username, password, fullName)
}

export async function logout(): Promise<void> {
  const currentToken = token.value
  try {
    if (currentToken) await logoutApi(currentToken)
  } finally {
    clearAuth()
  }
}

function clearAuth(): void {
  token.value = undefined
  currentUser.value = undefined
  localStorage.removeItem(STORAGE_KEY)
}
