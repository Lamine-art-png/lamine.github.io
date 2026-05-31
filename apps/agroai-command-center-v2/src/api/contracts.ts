// Typed API contracts for the AGRO-AI Workbench backend.
// These mirror the FastAPI models in agroai_api/app/models/workbench.py and the
// truthful status fields added in this rebuild.

export type BackendStatus = "available" | "limited" | "unavailable";

export type AnalysisMode = "representative" | "uploaded" | "live";

export type RecommendationOrigin =
  | "representative_fallback"
  | "deterministic_engine"
  | "live_intelligence_engine"
  | "uploaded_intelligence_engine";

export type ContextOrigin = "representative" | "uploaded" | "live";

export type SourceStatus = "Matched" | "Accepted" | "Pending" | "Pending target" | "Review" | "Connected source";

export interface SourceRow {
  source: string;
  latestSignal: string;
  records: string;
  contribution: string;
  status: SourceStatus;
}

export interface ReconciliationRow {
  source: string;
  signal: string;
  interpretation: string;
  status: SourceStatus;
}

export type ChainStepStatus = "Complete" | "Pending";

export interface EvidenceStep {
  key: "recommended" | "scheduled" | "applied" | "observed" | "verified";
  label: string;
  status: ChainStepStatus;
  owner: string;
  timestamp: string;
  evidence: string;
}

export interface TraceStep {
  title: string;
  status: "complete" | "running" | "pending" | "review";
  recordsProcessed: number;
  detail: string;
  timestamp: string;
}

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
  recommendationOrigin: RecommendationOrigin;
}

// ---- Raw backend response shapes (subset consumed by the UI) ----------

export interface WorkbenchSchemaResponse {
  supported_file_types?: string[];
  expected_fields?: Record<string, string[]>;
  output_schema?: string[];
}

export interface WorkbenchArtifact {
  artifact_id?: string;
  filename: string;
  content_type?: string;
  source_kind?: string;
  rows_detected?: number;
  columns_detected?: string[];
  parse_status?: string;
  warnings?: string[];
}

export interface WorkbenchReconciliation {
  matched_signals?: string[];
  conflicts_detected?: string[];
  missing_inputs?: string[];
  confidence_score?: number;
  confidence_label?: string;
  evidence_completeness?: string;
  planned_vs_applied_variance?: string;
  controller_event_validity?: string;
  flow_meter_agreement?: string;
  weather_demand?: string;
  soil_moisture_deficit?: string;
  field_observation_support?: string;
  satellite_stress_support?: string;
}

export interface WorkbenchAnalysisResult {
  analysis_id: string;
  session_id: string;
  status: string;
  data_sources?: Record<string, unknown>;
  normalized_context?: Record<string, unknown>;
  signal_summary?: Record<string, unknown>;
  reconciliation?: WorkbenchReconciliation;
  recommendation?: Record<string, unknown>;
  report_summary?: Record<string, unknown>;
  analysis_trace?: Array<{ title: string; status?: string; objects_processed?: number; details?: string }>;
  limitations?: string[];
  // Truthful status fields added in this rebuild:
  backend_status?: BackendStatus;
  analysis_mode?: AnalysisMode;
  recommendation_origin?: RecommendationOrigin;
  context_origin?: ContextOrigin;
  live_inputs_used?: string[];
  uploaded_artifacts_used?: string[];
  warnings?: string[];
}

export interface ApiResult<T> {
  ok: boolean;
  status: number;
  data: T | null;
  error?: string;
}
