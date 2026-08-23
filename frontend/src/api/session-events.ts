import { requestSessionApi } from "./sessions"
import type { EventsPage, SessionEvent, Surface, Trace, Trajectory } from "../types/session-event"

export function fetchSessionEvents(sessionId: string, afterSeq = -1, limit = 100): Promise<EventsPage> {
  return requestSessionApi<EventsPage>(
    `/api/sessions/${sessionId}/events?afterSeq=${afterSeq}&limit=${limit}`,
  )
}

export function fetchSessionEvent(sessionId: string, seq: number): Promise<SessionEvent> {
  return requestSessionApi<SessionEvent>(`/api/sessions/${sessionId}/events/${seq}`)
}

export function fetchSessionSurface(sessionId: string, asOfSeq?: number): Promise<Surface> {
  const query = typeof asOfSeq === "number" ? `?asOfSeq=${asOfSeq}` : ""
  return requestSessionApi<Surface>(`/api/sessions/${sessionId}/surface${query}`)
}

export function fetchSessionTrajectory(sessionId: string): Promise<Trajectory> {
  return requestSessionApi<Trajectory>(`/api/sessions/${sessionId}/trajectory`)
}

export function fetchSessionTrace(sessionId: string, runId: string): Promise<Trace> {
  return requestSessionApi<Trace>(
    `/api/sessions/${sessionId}/trace?run_id=${encodeURIComponent(runId)}`,
  )
}
