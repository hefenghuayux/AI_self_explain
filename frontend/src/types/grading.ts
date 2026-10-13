export type GradingStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED"
export interface GradingAmbiguityNote { source: string; interpretation: string; impact: string }
export interface GradingReport { correctnessScore: number; correctnessReason: string; completenessScore: number; completenessReason: string; missingRequirements: string[]; totalScore: number; ambiguityNotes: GradingAmbiguityNote[]; rubricLimitations: string[]; summary: string }
export interface GradingStudentStep { seq: number; stepContent: string | null; explainTranscript: string | null }
export interface Grading { id: number; attemptId: number; status: GradingStatus; evaluationStatus: GradingStatus; evaluationError: string | null; errorMessage: string | null; acknowledgedAt: string | null; report: GradingReport | null; createdAt: string; standardVersion: string; studentSteps?: GradingStudentStep[] }
