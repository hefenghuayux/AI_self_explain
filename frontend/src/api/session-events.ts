import { requestSessionApi } from "./sessions"
import type { Surface, Trajectory } from "../types/session-event"

/** 轨迹页只消费 /trajectory；/surface 仅供详情面板按 surfaceSeq 重建模型上下文。 */
export function fetchSessionTrajectory(sessionId: string): Promise<Trajectory> {
  return requestSessionApi<Trajectory>(`/api/sessions/${sessionId}/trajectory`)
}

export function fetchSessionSurface(sessionId: string, asOfSeq?: number): Promise<Surface> {
  const query = typeof asOfSeq === "number" ? `?asOfSeq=${asOfSeq}` : ""
  return requestSessionApi<Surface>(`/api/sessions/${sessionId}/surface${query}`)
}
