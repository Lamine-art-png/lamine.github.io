import type { DecisionAction, DecisionOutput, ReasoningToken, RiskFlags } from "../../schemas/decision";
import type { NormalizedSignalPack } from "../../schemas/signals";
import { scoreConfidence } from "../confidence/score";
import { evaluateRiskFlags } from "../risk/flags";
import { selectTimingWindow } from "./timing";
import { calculateRecommendedVolume } from "./volume";
import { ACTION_THRESHOLDS, MODEL_VERSION, priorityFromScore, RULES_VERSION } from "./rules";

export interface DecisionEngineInput {
  signalPack: NormalizedSignalPack;
  inputHash: string;
  createdAt?: string;
}

export function runDecisionEngine(input: DecisionEngineInput): DecisionOutput {
  const pack = input.signalPack;
  const scores = pack.confidence_inputs.component_scores;
  const riskFlags = evaluateRiskFlags(pack);
  const action = selectAction(pack, riskFlags);
  const priority = priorityFromScore(scores.priority_score);
  const timing = selectTimingWindow(pack);
  const volume = calculateRecommendedVolume(pack);
  const confidence = scoreConfidence(pack, riskFlags);
  const tokens = reasoningTokens(pack, riskFlags);

  return {
    decision_id: crypto.randomUUID(),
    field_id: pack.field_id,
    recommendation: {
      action,
      priority,
      recommended_window_start: timing.recommended_window_start,
      recommended_window_end: timing.recommended_window_end,
      recommended_volume: action === "irrigate" ? volume.recommended_volume : 0,
      recommended_volume_unit: volume.recommended_volume_unit,
      estimated_duration: action === "irrigate" ? volume.estimated_duration : 0,
      estimated_duration_unit: volume.estimated_duration_unit,
      irrigation_method_assumption: volume.irrigation_method_assumption,
    },
    rationale: {
      executive_summary: "",
      agronomic_reasoning: "",
      signal_evidence: tokens.map((token) => token.kind === "signal" ? `${token.name}:${token.value}` : token.id),
      water_balance_reasoning: "",
      anomaly_reasoning: "",
    },
    confidence,
    risk_flags: riskFlags,
    reporting: {
      projected_water_savings: action === "irrigate" ? "Estimated 8-14% savings versus a fixed calendar irrigation." : "No irrigation volume committed in this decision.",
      operational_note: "",
      advisor_note: "",
      grower_facing_message: "",
      compliance_note: "Decision trace includes provider, rules version, input hash, and audit reference.",
    },
    trace: {
      model_version: MODEL_VERSION,
      rules_version: RULES_VERSION,
      provider: "earthdaily",
      input_hash: input.inputHash,
      created_at: input.createdAt ?? new Date().toISOString(),
    },
    reasoning_tokens: tokens,
  };
}

export function selectAction(pack: NormalizedSignalPack, flags: RiskFlags): DecisionAction {
  const scores = pack.confidence_inputs.component_scores;
  const dataReviewFlags = [flags.data_gap, flags.cloud_contamination, flags.sensor_conflict].filter(Boolean).length;
  if (scores.data_quality_score < ACTION_THRESHOLDS.poor_data_quality ||
      dataReviewFlags >= ACTION_THRESHOLDS.risk_flag_review_count) {
    return "investigate";
  }

  if (strongConflictingSignals(pack, flags)) return "manual_review";

  if (scores.priority_score >= ACTION_THRESHOLDS.irrigate_priority &&
      scores.moisture_stress_score >= ACTION_THRESHOLDS.irrigate_moisture_stress &&
      !flags.over_irrigation_risk) {
    return "irrigate";
  }

  if (scores.priority_score >= ACTION_THRESHOLDS.monitor_priority_min &&
      scores.priority_score < ACTION_THRESHOLDS.monitor_priority_max) {
    return "monitor";
  }

  if (scores.priority_score < ACTION_THRESHOLDS.wait_priority &&
      scores.moisture_stress_score < ACTION_THRESHOLDS.moisture_sufficient) {
    return "wait";
  }

  return "monitor";
}

function strongConflictingSignals(pack: NormalizedSignalPack, flags: RiskFlags): boolean {
  const scores = pack.confidence_inputs.component_scores;
  const dryVegetation = pack.vegetation_context.ndmi_level < 0.24 || scores.vegetation_stress_score > 0.65;
  const wetWaterBalance = scores.moisture_stress_score < 0.24 && pack.water_context.water_stress_index < 0.25;
  return flags.sensor_conflict || (dryVegetation && wetWaterBalance);
}

function reasoningTokens(pack: NormalizedSignalPack, flags: RiskFlags): ReasoningToken[] {
  const scores = pack.confidence_inputs.component_scores;
  return [
    { kind: "signal", name: "moisture_stress_score", value: scores.moisture_stress_score, weight: 0.3, impact: signalImpact(scores.moisture_stress_score) },
    { kind: "signal", name: "et_pressure_score", value: scores.et_pressure_score, weight: 0.25, impact: signalImpact(scores.et_pressure_score) },
    { kind: "signal", name: "vegetation_stress_score", value: scores.vegetation_stress_score, weight: 0.2, impact: signalImpact(scores.vegetation_stress_score) },
    { kind: "signal", name: "anomaly_severity", value: scores.anomaly_severity, weight: 0.15, impact: signalImpact(scores.anomaly_severity) },
    { kind: "signal", name: "weather_risk_score", value: scores.weather_risk_score, weight: 0.1, impact: signalImpact(scores.weather_risk_score) },
    { kind: "rule", id: "data_quality_guard", triggered: scores.data_quality_score < ACTION_THRESHOLDS.poor_data_quality, description: "Low quality data routes the decision to investigation." },
    { kind: "rule", id: "irrigation_threshold", triggered: scores.priority_score >= ACTION_THRESHOLDS.irrigate_priority, description: "Priority and moisture stress clear irrigation threshold." },
    { kind: "rule", id: "over_irrigation_guard", triggered: flags.over_irrigation_risk, description: "Suppress irrigation if water balance indicates excess moisture." },
    { kind: "constraint", id: "rules_version", value: RULES_VERSION },
    { kind: "constraint", id: "provider", value: pack.provider_trace.provider },
  ];
}

function signalImpact(value: number): "positive" | "negative" {
  return value >= 0.45 ? "negative" : "positive";
}

