export type EventType =
  | "session.started"
  | "user.message"
  | "context.added"
  | "model.requested"
  | "model.responded"
  | "model.failed"
  | "state.changed"

export interface SessionEvent {
  sessionId: number
  seq: number
  eventId: string
  runId?: string
  parentEventId?: string
  eventType: EventType
  occurredAt: string
  data: Record<string, unknown>
}

export interface EventsPage {
  sessionId: number
  events: SessionEvent[]
  nextAfterSeq: number
}

export interface SurfaceMessage {
  seq: number
  role: "user"
  content: string
}

export interface SurfaceContext {
  seq: number
  kind: "question" | "rubric" | "session_state" | "memory"
  source: string
  content: string | Record<string, unknown>
}

export interface Surface {
  sessionId: number
  asOfSeq: number
  messages: SurfaceMessage[]
  contexts: SurfaceContext[]
}

export interface UserInputStep {
  kind: "user_input"
  eventSeq: number
  summary: string
}

export interface ModelCallStep {
  kind: "model_call"
  requestSeq: number
  resultSeq?: number
  status: "pending" | "success" | "failed"
  durationMs?: number
}

export interface StateChangeStep {
  kind: "state_change"
  eventSeq: number
  from: string
  to: string
}

export type TrajectoryStep = UserInputStep | ModelCallStep | StateChangeStep

export interface TrajectoryRun {
  runId: string
  startedAt: string
  steps: TrajectoryStep[]
}

export interface Trajectory {
  sessionId: number
  runs: TrajectoryRun[]
}

export interface TraceNode {
  seq: number
  eventType: EventType
  children: TraceNode[]
}

export interface Trace {
  sessionId: number
  runId: string
  roots: TraceNode[]
}
