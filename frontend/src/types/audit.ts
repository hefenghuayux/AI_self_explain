export interface TraceCorrelation {
  sessionId: number
  requestId?: string
}

export interface TraceResult {
  status: string
  durationMs?: number
  error?: {
    type: string
    message: string
  }
}

export interface TraceEvent {
  eventId: string
  sequence: number
  occurredAt: string
  eventName: string
  severity: string
  correlation: TraceCorrelation
  operation: Record<string, unknown>
  result: TraceResult
  data: Record<string, unknown>
  references: Record<string, unknown>
  privacy?: Record<string, unknown>
}

export interface SessionTrace {
  schemaVersion: string
  producer: {
    service: string
    version: string
  }
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
