import type { EarthDailyRawInput, TimeSeriesPoint } from "../../schemas/earthdaily";

export function clamp(value: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, value));
}

export function round(value: number, digits = 3): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

export function sumSeries(points: TimeSeriesPoint[], days?: number): number {
  const slice = typeof days === "number" ? points.slice(0, days) : points;
  return round(slice.reduce((total, point) => total + point.value, 0), 3);
}

export function maxSeries(points: TimeSeriesPoint[], days?: number): number {
  const slice = typeof days === "number" ? points.slice(0, days) : points;
  return slice.reduce((max, point) => Math.max(max, point.value), Number.NEGATIVE_INFINITY);
}

export function latestPoint(points: TimeSeriesPoint[]): TimeSeriesPoint | null {
  return points.length ? points[points.length - 1] : null;
}

export function slope(points: TimeSeriesPoint[], days = 14): number {
  const subset = points.slice(-days);
  if (subset.length < 2) return 0;
  const first = subset[0].value;
  const last = subset[subset.length - 1].value;
  return round((last - first) / (subset.length - 1), 4);
}

export function parseFreshnessHours(value: string): number {
  const trimmed = value.trim().toLowerCase();
  const match = trimmed.match(/^(\d+(?:\.\d+)?)(h|hr|hrs|hour|hours|d|day|days)$/);
  if (!match) return 24;
  const amount = Number(match[1]);
  const unit = match[2];
  return unit.startsWith("d") ? amount * 24 : amount;
}

export function plantAvailableWaterMm(raw: EarthDailyRawInput): number {
  return round(raw.field.soil_profile.awc_mm_per_m * raw.field.soil_profile.rooting_depth_m, 2);
}

export function moistureStressScore(raw: EarthDailyRawInput): number {
  const soil = raw.field.soil_profile;
  const paw = plantAvailableWaterMm(raw);
  const depletionRatio = paw > 0 ? raw.water_context.estimated_depletion / paw : 0;
  const relativeMoisture = (raw.water_context.soil_moisture_rootzone - soil.wilting_point) /
    Math.max(soil.field_capacity - soil.wilting_point, 0.01);
  const drynessFromRootzone = 1 - clamp(relativeMoisture);
  return round(clamp(0.58 * depletionRatio + 0.42 * drynessFromRootzone));
}

export function etPressureScore(raw: EarthDailyRawInput): number {
  const forecastEt = sumSeries(raw.weather.et_forecast, 7);
  const forecastPrecip = sumSeries(raw.weather.precipitation, 7);
  return round(clamp((forecastEt - forecastPrecip) / 55));
}

export function vegetationStressScore(raw: EarthDailyRawInput): number {
  const ndviSlope = slope(raw.time_series.ndvi, 14);
  const ndreSlope = slope(raw.time_series.ndre, 14);
  const ndmi = raw.imagery.vegetation_indices.ndmi_mean;
  const slopePenalty = clamp((-ndviSlope * 45) + (-ndreSlope * 55));
  const ndmiPenalty = clamp((0.42 - ndmi) / 0.3);
  return round(clamp(0.55 * slopePenalty + 0.45 * ndmiPenalty));
}

export function anomalySeverity(raw: EarthDailyRawInput): number {
  const hotspot = raw.agronomic_events.hotspot_alerts.reduce((max, alert) => Math.max(max, alert.severity), 0);
  const change = raw.agronomic_events.change_detection.reduce((max, item) => Math.max(max, item.magnitude), 0);
  const layer = raw.imagery.anomaly_layers.reduce((max, item) => Math.max(max, item.severity), 0);
  return round(clamp(Math.max(layer, hotspot * 1.05, change * 0.9)));
}

export function weatherRiskScore(raw: EarthDailyRawInput): number {
  const heatDays = raw.weather.temperature_max.slice(0, 7).filter((point) => point.value > 35).length;
  const maxWind = maxSeries(raw.weather.wind_speed, 7);
  const precipDays = raw.weather.precipitation.slice(0, 7).filter((point) => point.value >= 5).length;
  const noRainPressure = precipDays === 0 ? 0.35 : 0;
  return round(clamp((heatDays / 7) * 0.55 + clamp((maxWind - 4) / 5) * 0.1 + noRainPressure));
}

export function dataQualityScore(raw: EarthDailyRawInput): number {
  const freshnessHours = parseFreshnessHours(raw.metadata.data_freshness);
  const cloudPenalty = clamp(raw.imagery.cloud_cover / 0.65) * 0.42;
  const missingPenalty = clamp(raw.metadata.missing_fields.length / 6) * 0.32;
  const freshnessPenalty = clamp(freshnessHours / 96) * 0.26;
  return round(clamp(1 - cloudPenalty - missingPenalty - freshnessPenalty));
}

export function priorityScore(raw: EarthDailyRawInput): number {
  const moisture = moistureStressScore(raw);
  const et = etPressureScore(raw);
  const veg = vegetationStressScore(raw);
  const anomaly = anomalySeverity(raw);
  const weather = weatherRiskScore(raw);
  const quality = dataQualityScore(raw);
  const rawScore = 0.3 * moisture + 0.25 * et + 0.2 * veg + 0.15 * anomaly + 0.1 * weather;
  return round(clamp(rawScore * (0.5 + 0.5 * quality)));
}

export function signalAgreementScore(raw: EarthDailyRawInput): number {
  const stressIndicators = [
    moistureStressScore(raw) >= 0.45,
    etPressureScore(raw) >= 0.55,
    vegetationStressScore(raw) >= 0.38,
    raw.water_context.water_stress_index >= 0.42,
    anomalySeverity(raw) >= 0.5,
  ];
  const yes = stressIndicators.filter(Boolean).length;
  const no = stressIndicators.length - yes;
  return round(1 - Math.min(yes, no) / stressIndicators.length);
}

export function recencyScoreFromHours(hours: number): number {
  return round(clamp(1 - hours / 96));
}

