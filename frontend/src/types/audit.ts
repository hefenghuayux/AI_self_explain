export interface TraceCorrelation {
  sessionId: number
  requestId: string | null
  traceId: string
  spanId: string
  parentSpanId: string | null
}

export interface TraceResult {
  status: string
  durationMs: number | null
  errorType: string | null
  errorMessage: string | null
}

export interface TraceEvent {
  schemaVersion: string
  eventId: string
  sequence: number
  occurredAt: string
  eventName: string
  severity: string
  source: Record<string, unknown>
  correlation: TraceCorrelation
  operation: Record<string, unknown>
  result: TraceResult
  data: Record<string, unknown>
  references: Record<string, unknown>
  privacy: Record<string, unknown>
}

export interface SessionTrace {
  schemaVersion: string
  sessionId: number
  generatedAt: string
  summary: {
    status: string
    flowStage: string
    round: number
    eventCount: number
    errorCount: number
    externalCallCount: number
  }
  events: TraceEvent[]
}

export interface AuditExport {
  sessionId: number
  jsonlPath: string
  markdownPath: string
  eventCount: number
}
