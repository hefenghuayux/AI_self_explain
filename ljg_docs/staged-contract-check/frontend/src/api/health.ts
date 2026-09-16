import type { HealthResponse } from "../types/health"

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch("/api/health")
  if (!response.ok) {
    throw new Error(`健康检查失败：HTTP ${response.status}`)
  }
  return (await response.json()) as HealthResponse
}
