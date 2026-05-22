import type { ConfidenceLevel, RiskFlags } from "../../schemas/decision";
import type { NormalizedSignalPack } from "../../schemas/signals";
import { round } from "../normalization/derive";

export interface ConfidenceScore {
  score: number;
  level: ConfidenceLevel;
  drivers: string[];
  limitations: string[];
}

export function scoreConfidence(pack: NormalizedSignalPack, flags: RiskFlags): ConfidenceScore {
  const inputs = pack.confidence_inputs;
  const score = round(
    0.4 * inputs.component_scores.data_quality_score +
      0.3 * inputs.signal_agreement +
      0.2 * inputs.recency_score +
      0.1 * inputs.model_self_consistency,
  );

  return {
    score,
    level: confidenceLevel(score),
    drivers: selectDrivers(pack, flags),
    limitations: selectLimitations(pack, flags),
  };
}

export function confidenceLevel(score: number): ConfidenceLevel {
  if (score < 0.45) return "low";
  if (score < 0.7) return "medium";
  if (score < 0.85) return "high";
  return "very_high";
}

function selectDrivers(pack: NormalizedSignalPack, flags: RiskFlags): string[] {
  const candidates: Array<[number, string]> = [
    [pack.data_quality.score, "Clear EarthDaily scene and complete required data fields."],
    [pack.confidence_inputs.signal_agreement, "Moisture, vegetation, ET, and anomaly signals are directionally aligned."],
    [pack.confidence_inputs.recency_score, "Imagery and weather context are recent enough for operational use."],
    [pack.provider_trace.stac_item_count > 0 ? 0.8 : 0.2, "STAC imagery reference is present for report traceability."],
    [flags.sensor_conflict ? 0.1 : 0.7, "No material sensor conflict was detected."],
  ];
  return candidates
    .sort((a, b) => b[0] - a[0])
    .slice(0, 3)
    .map(([, label]) => label);
}

function selectLimitations(pack: NormalizedSignalPack, flags: RiskFlags): string[] {
  const candidates: Array<[number, string]> = [
    [1 - pack.data_quality.score, "Data quality is limited by cloud cover, missing fields, or stale inputs."],
    [pack.data_quality.missing_fields.length / 3, `Missing fields: ${pack.data_quality.missing_fields.join(", ") || "none"}.`],
    [pack.anomaly_context.cloud_cover, "Cloud contamination may reduce imagery confidence."],
    [flags.sensor_conflict ? 1 : 0, "Field moisture and vegetation signals conflict and require review."],
    [pack.confidence_inputs.recency_score < 0.55 ? 0.7 : 0, "Input freshness is approaching the edge of the decision window."],
  ];
  return candidates
    .filter(([score]) => score > 0)
    .sort((a, b) => b[0] - a[0])
    .slice(0, 3)
    .map(([, label]) => label);
}

