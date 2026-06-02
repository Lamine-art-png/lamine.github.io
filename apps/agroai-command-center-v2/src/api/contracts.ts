export type BackendStatus = "live" | "limited" | "unavailable";
export type AnalysisMode = "representative" | "uploaded" | "live";
export type RecommendationOrigin = "representative_fallback" | "deterministic_engine" | "live_intelligence_engine";

export interface Decision {
  action: string;
  start: string;
  appliedWater: string;
  crop: string;
  block: string;
  driver: string;
  confidence: string;
  evidenceCompleteness: string;
  estimatedWaterSavings: string;
  verification: string;
  recommendationOrigin?: RecommendationOrigin;
}
export interface SourceRow { source: string; latestSignal: string; records: string; contribution: string; status: string; }
export interface ReconciliationRow { source: string; signal: string; interpretation: string; status: "Matched" | "Review" | "Pending" | "Pending target"; }
export interface TraceStep { title: string; status: "pending" | "complete" | "review"; recordsProcessed: number; detail: string; timestamp: string; }
export interface EvidenceStep { key: "recommended" | "scheduled" | "applied" | "observed" | "verified"; label: string; owner: string; status: "Pending" | "Complete"; timestamp: string; evidence: string; }
export interface WorkbenchAnalysisResult {
  recommendation?: Record<string, unknown>;
  report_summary?: Record<string, unknown>;
  recommendation_origin?: RecommendationOrigin;
  reconciliation?: { evidence_completeness?: number | string };
  analysis_trace?: Array<{ title: string; status?: string; objects_processed?: number; details?: string }>;
}
