import type { RiskFlags } from "../../schemas/decision";
import type { NormalizedSignalPack } from "../../schemas/signals";

export interface RiskThresholds {
  water_stress_index: number;
  moisture_score: number;
  heat_temp_c: number;
  cloud_cover: number;
  anomaly_severity: number;
  over_irrigation_rootzone_fraction: number;
  under_irrigation_depletion_fraction: number;
  sensor_conflict_gap: number;
}

export const DEFAULT_RISK_THRESHOLDS: RiskThresholds = {
  water_stress_index: 0.5,
  moisture_score: 0.45,
  heat_temp_c: 35,
  cloud_cover: 0.35,
  anomaly_severity: 0.5,
  over_irrigation_rootzone_fraction: 0.92,
  under_irrigation_depletion_fraction: 0.32,
  sensor_conflict_gap: 0.42,
};

export function evaluateRiskFlags(pack: NormalizedSignalPack): RiskFlags {
  const scores = pack.confidence_inputs.component_scores;
  const rootzone = pack.water_context.soil_moisture_rootzone;
  const paw = pack.water_context.plant_available_water_mm;
  const depletionFraction = paw > 0 ? pack.water_context.estimated_depletion_mm / paw : 0;
  const highStressSignals = [
    scores.moisture_stress_score >= DEFAULT_RISK_THRESHOLDS.moisture_score,
    pack.water_context.water_stress_index >= DEFAULT_RISK_THRESHOLDS.water_stress_index,
    pack.vegetation_context.ndmi_level < 0.26,
  ].filter(Boolean).length;
  const lowStressSignals = [
    scores.moisture_stress_score < 0.25,
    pack.water_context.water_stress_index < 0.25,
    pack.vegetation_context.ndmi_level > 0.42,
  ].filter(Boolean).length;

  return {
    water_stress: pack.water_context.water_stress_index >= DEFAULT_RISK_THRESHOLDS.water_stress_index ||
      scores.moisture_stress_score >= DEFAULT_RISK_THRESHOLDS.moisture_score,
    heat_stress: pack.weather_context.series.temperature_max
      .slice(0, 7)
      .some((point) => point.value >= DEFAULT_RISK_THRESHOLDS.heat_temp_c),
    data_gap: pack.data_quality.missing_fields.length > 0 || pack.data_quality.score < 0.45,
    cloud_contamination: pack.anomaly_context.cloud_cover >= DEFAULT_RISK_THRESHOLDS.cloud_cover,
    anomaly_detected: pack.anomaly_context.max_anomaly_severity >= DEFAULT_RISK_THRESHOLDS.anomaly_severity,
    over_irrigation_risk: rootzone >= DEFAULT_RISK_THRESHOLDS.over_irrigation_rootzone_fraction * 0.31 &&
      depletionFraction < 0.18,
    under_irrigation_risk: depletionFraction >= DEFAULT_RISK_THRESHOLDS.under_irrigation_depletion_fraction ||
      scores.et_pressure_score >= 0.7,
    sensor_conflict: highStressSignals > 0 && lowStressSignals > 0 &&
      Math.abs(scores.moisture_stress_score - pack.water_context.water_stress_index) >= DEFAULT_RISK_THRESHOLDS.sensor_conflict_gap,
  };
}

export function riskFlagSummary(flags: RiskFlags): string[] {
  return Object.entries(flags)
    .filter(([, active]) => active)
    .map(([name]) => name);
}

