import { requestSessionApi } from "./sessions"
import type { AuditExport, SessionTrace } from "../types/audit"

export function fetchSessionTrace(sessionId: string): Promise<SessionTrace> {
  return requestSessionApi<SessionTrace>(`/api/sessions/${sessionId}/audit/trace`)
}

export function exportSessionTrace(sessionId: string): Promise<AuditExport> {
  return requestSessionApi<AuditExport>(`/api/sessions/${sessionId}/audit/export`, {
    method: "POST",
  })
}
