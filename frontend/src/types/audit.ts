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

export interface ModelRequestSnapshot {
  schemaVersion: "1.0"
  purpose: "AI_EVALUATION" | "AI_SUPPORT" | "GUIDED_ANSWER_ASSESSMENT"
  promptVersion: string
  blocks: {
    systemInstructions: string
    questionContext: Record<string, unknown>
    sessionContext: Record<string, unknown>
    memoryContext?: Record<string, unknown>
    userInput: Record<string, unknown>
    retryContext: Record<string, unknown>
  }
  transport: {
    model: string
    messages: Array<{ role: "user"; content: string }>
    response_format: Record<string, unknown>
  }
  privacy: {
    containsStudentContent: boolean
    containsAnswerMaterial: boolean
    containsMemory: boolean
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
