export type DecisionAction = "irrigate" | "wait" | "monitor" | "investigate" | "manual_review";
export type DecisionPriority = "low" | "medium" | "high" | "critical";
export type ConfidenceLevel = "low" | "medium" | "high" | "very_high";

export interface RiskFlags {
  water_stress: boolean;
  heat_stress: boolean;
  data_gap: boolean;
  cloud_contamination: boolean;
  anomaly_detected: boolean;
  over_irrigation_risk: boolean;
  under_irrigation_risk: boolean;
  sensor_conflict: boolean;
}

export type ReasoningToken =
  | { kind: "signal"; name: string; value: number; weight: number; impact: "positive" | "negative" }
  | { kind: "rule"; id: string; triggered: boolean; description: string }
  | { kind: "constraint"; id: string; value: string };

export interface DecisionOutput {
  decision_id: string;
  field_id: string;
  recommendation: {
    action: DecisionAction;
    priority: DecisionPriority;
    recommended_window_start: string;
    recommended_window_end: string;
    recommended_volume: number;
    recommended_volume_unit: string;
    estimated_duration: number;
    estimated_duration_unit: string;
    irrigation_method_assumption: string;
  };
  rationale: {
    executive_summary: string;
    agronomic_reasoning: string;
    signal_evidence: string[];
    water_balance_reasoning: string;
    anomaly_reasoning: string;
  };
  confidence: {
    score: number;
    level: ConfidenceLevel;
    drivers: string[];
    limitations: string[];
  };
  risk_flags: RiskFlags;
  reporting: {
    projected_water_savings: string;
    operational_note: string;
    advisor_note: string;
    grower_facing_message: string;
    compliance_note: string;
  };
  trace: {
    model_version: string;
    rules_version: string;
    provider: "earthdaily";
    input_hash: string;
    created_at: string;
  };
  reasoning_tokens?: ReasoningToken[];
}

export function isDecisionOutput(value: unknown): value is DecisionOutput {
  return typeof value === "object" && value !== null && typeof (value as DecisionOutput).decision_id === "string";
}

