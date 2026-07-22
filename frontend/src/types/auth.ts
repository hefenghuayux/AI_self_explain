export type UserRole = "STUDENT" | "TEACHER"

export interface User {
  id: number
  username: string
  fullName: string
  role: UserRole
}

export interface AuthResponse {
  token: string
  expiresAt: string
  user: User
}
