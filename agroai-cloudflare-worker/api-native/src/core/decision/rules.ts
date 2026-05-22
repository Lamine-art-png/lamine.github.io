import type { DecisionPriority } from "../../schemas/decision";
import type { RiskThresholds } from "../risk/flags";

export const RULES_VERSION = "earthdaily-irrigation-rules-v1.0.0";
export const MODEL_VERSION = "agroai-deterministic-irrigation-v1";

export const COMPONENT_WEIGHTS = {
  moisture_stress_score: 0.3,
  et_pressure_score: 0.25,
  vegetation_stress_score: 0.2,
  anomaly_severity: 0.15,
  weather_risk_score: 0.1,
} as const;

export const PRIORITY_BUCKETS: Array<{ min: number; max: number; priority: DecisionPriority }> = [
  { min: 0, max: 0.25, priority: "low" },
  { min: 0.25, max: 0.55, priority: "medium" },
  { min: 0.55, max: 0.8, priority: "high" },
  { min: 0.8, max: 1.01, priority: "critical" },
];

export const ACTION_THRESHOLDS = {
  poor_data_quality: 0.35,
  risk_flag_review_count: 3,
  irrigate_priority: 0.55,
  irrigate_moisture_stress: 0.45,
  monitor_priority_min: 0.25,
  monitor_priority_max: 0.55,
  wait_priority: 0.25,
  moisture_sufficient: 0.28,
  strong_conflict_gap: 0.48,
} as const;

export const RISK_THRESHOLDS: RiskThresholds = {
  water_stress_index: 0.5,
  moisture_score: 0.45,
  heat_temp_c: 35,
  cloud_cover: 0.35,
  anomaly_severity: 0.5,
  over_irrigation_rootzone_fraction: 0.92,
  under_irrigation_depletion_fraction: 0.32,
  sensor_conflict_gap: 0.42,
};

export const KC_STAGE: Record<string, Record<string, number>> = {
  almonds: {
    "early-season": 0.55,
    "mid-season": 0.92,
    "late-season": 0.78,
    default: 0.82,
  },
  grapes: {
    "early-season": 0.42,
    "mid-season": 0.72,
    "late-season": 0.58,
    default: 0.62,
  },
  corn: {
    "early-season": 0.42,
    "mid-season": 1.12,
    "late-season": 0.74,
    default: 0.9,
  },
  alfalfa: {
    "early-season": 0.85,
    "mid-season": 1.05,
    "late-season": 0.95,
    default: 0.98,
  },
  tomato: {
    "early-season": 0.55,
    "mid-season": 1.08,
    "late-season": 0.82,
    default: 0.88,
  },
};

export const METHOD_EFFICIENCY: Record<string, number> = {
  drip: 0.9,
  sprinkler: 0.75,
  flood: 0.55,
};

export const METHOD_MAX_MM: Record<string, number> = {
  drip: 55,
  sprinkler: 42,
  flood: 85,
};

export const METHOD_APPLICATION_RATE_MM_PER_HOUR: Record<string, number> = {
  drip: 2.3,
  sprinkler: 5.2,
  flood: 9,
};

export function priorityFromScore(score: number): DecisionPriority {
  return PRIORITY_BUCKETS.find((bucket) => score >= bucket.min && score < bucket.max)?.priority ?? "critical";
}

export function cropCoefficient(cropType: string, cropStage: string): number {
  const crop = KC_STAGE[normalizeKey(cropType)] ?? KC_STAGE.almonds;
  return crop[normalizeKey(cropStage)] ?? crop.default;
}

export function normalizeKey(value: string): string {
  return value.trim().toLowerCase().replaceAll("_", "-");
}

