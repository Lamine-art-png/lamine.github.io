import type { EarthDailyRawInput } from "../../schemas/earthdaily";
import type { ComponentScores, NormalizedSignalPack } from "../../schemas/signals";
import {
  anomalySeverity,
  dataQualityScore,
  etPressureScore,
  latestPoint,
  moistureStressScore,
  parseFreshnessHours,
  plantAvailableWaterMm,
  priorityScore,
  recencyScoreFromHours,
  round,
  signalAgreementScore,
  slope,
  sumSeries,
  vegetationStressScore,
  weatherRiskScore,
} from "./derive";

export function normalizeEarthDailyInput(raw: EarthDailyRawInput): NormalizedSignalPack {
  const freshnessHours = parseFreshnessHours(raw.metadata.data_freshness);
  const component_scores: ComponentScores = {
    moisture_stress_score: moistureStressScore(raw),
    et_pressure_score: etPressureScore(raw),
    vegetation_stress_score: vegetationStressScore(raw),
    anomaly_severity: anomalySeverity(raw),
    weather_risk_score: weatherRiskScore(raw),
    data_quality_score: dataQualityScore(raw),
    priority_score: priorityScore(raw),
  };

  return {
    signal_pack_id: crypto.randomUUID(),
    field_id: raw.field.field_id,
    crop_context: {
      crop_type: raw.field.crop_type,
      crop_stage: raw.field.crop_stage,
      acreage: raw.field.acreage,
      region: raw.field.region,
      timezone: raw.field.timezone,
    },
    spatial_context: {
      geometry: raw.field.geometry,
      field_name: raw.field.field_name,
      grower_id: raw.field.grower_id,
      farm_id: raw.field.farm_id,
    },
    weather_context: {
      forecast_days: raw.weather.forecast_days,
      precipitation_7d_mm: sumSeries(raw.weather.precipitation, 7),
      et0_7d_mm: sumSeries(raw.weather.et0, 7),
      et_forecast_7d_mm: sumSeries(raw.weather.et_forecast, 7),
      heat_days_7d: raw.weather.temperature_max.slice(0, 7).filter((point) => point.value > 35).length,
      max_wind_speed_7d: Math.max(...raw.weather.wind_speed.slice(0, 7).map((point) => point.value)),
      series: raw.weather,
    },
    water_context: {
      soil_moisture_surface: raw.water_context.soil_moisture_surface,
      soil_moisture_rootzone: raw.water_context.soil_moisture_rootzone,
      estimated_depletion_mm: raw.water_context.estimated_depletion,
      water_stress_index: raw.water_context.water_stress_index,
      plant_available_water_mm: plantAvailableWaterMm(raw),
      irrigation_history: raw.water_context.irrigation_history,
      applied_water_actuals: raw.water_context.applied_water_actuals,
    },
    vegetation_context: {
      indices: raw.imagery.vegetation_indices,
      ndvi_14d_slope: slope(raw.time_series.ndvi, 14),
      ndre_14d_slope: slope(raw.time_series.ndre, 14),
      ndmi_level: raw.imagery.vegetation_indices.ndmi_mean,
      latest_series: {
        ndvi: latestPoint(raw.time_series.ndvi),
        ndmi: latestPoint(raw.time_series.ndmi),
        evi: latestPoint(raw.time_series.evi),
        ndre: latestPoint(raw.time_series.ndre),
        lai: latestPoint(raw.time_series.lai),
        biomass: latestPoint(raw.time_series.biomass),
        fapar: latestPoint(raw.time_series.fapar),
        fcover: latestPoint(raw.time_series.fcover),
      },
    },
    anomaly_context: {
      cloud_cover: raw.imagery.cloud_cover,
      anomaly_layers: raw.imagery.anomaly_layers,
      hotspot_alerts: raw.agronomic_events.hotspot_alerts,
      change_detection: raw.agronomic_events.change_detection,
      max_anomaly_severity: component_scores.anomaly_severity,
    },
    operational_context: {
      irrigation_method_assumption: inferIrrigationMethod(raw),
      acquisition_date: raw.imagery.acquisition_date,
      retrieved_at: raw.metadata.retrieved_at,
      data_freshness_hours: freshnessHours,
    },
    data_quality: {
      missing_fields: raw.metadata.missing_fields,
      quality_flags: raw.metadata.quality_flags,
      cloud_cover: raw.imagery.cloud_cover,
      freshness_hours: freshnessHours,
      score: component_scores.data_quality_score,
    },
    confidence_inputs: {
      component_scores,
      signal_agreement: signalAgreementScore(raw),
      recency_score: recencyScoreFromHours(freshnessHours),
      model_self_consistency: raw.metadata.quality_flags.includes("sensor_conflict") ? 0.62 : 0.91,
    },
    provider_trace: {
      provider: "earthdaily",
      mode: raw.mode,
      source: raw.metadata.source,
      stac_item_count: raw.imagery.stac_items.length,
      asset_links: raw.imagery.asset_links,
      index_maps: raw.imagery.index_maps,
    },
  };
}

function inferIrrigationMethod(raw: EarthDailyRawInput): string {
  const latest = raw.water_context.irrigation_history.at(-1);
  return latest?.method || (raw.field.crop_type === "alfalfa" ? "sprinkler" : "drip");
}

export function normalizedScoreRows(pack: NormalizedSignalPack) {
  const scores = pack.confidence_inputs.component_scores;
  return [
    ["Moisture stress", pack.water_context.estimated_depletion_mm, scores.moisture_stress_score],
    ["ET pressure", pack.weather_context.et_forecast_7d_mm, scores.et_pressure_score],
    ["Vegetation stress", pack.vegetation_context.ndmi_level, scores.vegetation_stress_score],
    ["Anomaly severity", pack.anomaly_context.max_anomaly_severity, scores.anomaly_severity],
    ["Weather risk", pack.weather_context.heat_days_7d, scores.weather_risk_score],
    ["Data quality", pack.data_quality.score, round(scores.data_quality_score)],
  ];
}

