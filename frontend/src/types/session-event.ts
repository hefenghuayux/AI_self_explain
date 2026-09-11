export type EventType =
  | "session.started"
  | "user.message"
  | "context.added"
  | "model.requested"
  | "model.responded"
  | "model.failed"
  | "state.changed"

/**
 * 事件、Surface、Trace 类型保留为后端接口契约的镜像。
 * 轨迹页不再调用 /events 与 /trace，但后端接口仍在，离线排查时按同一份契约读取。
 */
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

export type TrajectoryRecordKind =
  | "session"
  | "user"
  | "context"
  | "model_request"
  | "model_response"
  | "model_error"
  | "state_change"

export type TrajectoryRecordStatus = "complete" | "pending" | "failed"

export interface UserRecordDetail {
  text: string
  inputType: "text" | "voice"
}

export interface ContextRecordDetail {
  kind: "question" | "rubric" | "session_state" | "memory"
  source: string
  content: string | Record<string, unknown>
}

export interface ModelRequestRecordDetail {
  provider: string
  model: string
  messages: Array<Record<string, unknown>>
  surfaceSeq: number
}

export interface ModelResponseRecordDetail {
  output: Record<string, unknown>
  /** 历史事件可能没有保存模型原始回复，此时后端返回缺省键。 */
  rawContent?: string
  validation: "valid" | "invalid"
  inputTokens?: number
  outputTokens?: number
}

export interface ModelErrorRecordDetail {
  errorType: string
  message: string
}

export interface StateChangeRecordDetail {
  from: string
  to: string
  reason: string
}

export interface TrajectoryRecordDetail {
  session?: Record<string, never>
  user?: UserRecordDetail
  context?: ContextRecordDetail
  modelRequest?: ModelRequestRecordDetail
  modelResponse?: ModelResponseRecordDetail
  modelError?: ModelErrorRecordDetail
  stateChange?: StateChangeRecordDetail
}

export interface TrajectoryRecord {
  index: number
  eventSeq: number
  eventId: string
  eventType: EventType
  kind: TrajectoryRecordKind
  label: string
  summary: string
  status: TrajectoryRecordStatus
  /** 后端显式输出 null 表示该事件类型不记录耗时。 */
  durationMs?: number | null
  occurredAt: string
  parentEventId?: string
  detail: TrajectoryRecordDetail
}

export interface TrajectoryRun {
  runId: string
  startedAt: string
  steps: TrajectoryStep[]
  records: TrajectoryRecord[]
}

export interface Trajectory {
  sessionId: number
  runs: TrajectoryRun[]
  events: TrajectoryRecord[]
}

/** 后端 /trace 契约镜像；页面通过详情面板的父事件 / 直接结果跳转表达同一因果关系。 */
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
