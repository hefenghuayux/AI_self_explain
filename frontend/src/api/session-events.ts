import { requestSessionApi } from "./sessions"
import type { Trajectory } from "../types/session-event"

/** 轨迹页只消费 /trajectory；展开区展示后端投影好的 fullText，不再单独取 /surface。 */
export function fetchSessionTrajectory(sessionId: string): Promise<Trajectory> {
  return requestSessionApi<Trajectory>(`/api/sessions/${sessionId}/trajectory`)
}
