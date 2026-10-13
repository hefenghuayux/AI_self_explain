import type { Session } from "../types/session"
import type { Grading } from "../types/grading"
import { requestSessionApi } from "./sessions"
export interface GradedStepAttemptResponse { session: Session; grading: Grading }
export function submitGradedStepAttempt(sessionId: string, currentStepContent: string, version: number): Promise<GradedStepAttemptResponse> { return requestSessionApi<GradedStepAttemptResponse>(`/api/sessions/${sessionId}/graded-step-attempts`, { method: "POST", body: JSON.stringify({ currentStepContent, version }) }) }
export function fetchGrading(sessionId: string): Promise<Grading | null> { return requestSessionApi<Grading | null>(`/api/sessions/${sessionId}/grading`) }
export function retryGrading(sessionId: string): Promise<Grading> { return requestSessionApi<Grading>(`/api/sessions/${sessionId}/grading/retry`, { method: "POST" }) }
export function acknowledgeGrading(sessionId: string): Promise<Grading> { return requestSessionApi<Grading>(`/api/sessions/${sessionId}/grading/acknowledge`, { method: "POST" }) }
