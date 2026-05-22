import {
  hasInvalidNumber,
  isFiniteNumber,
  isRecord,
  optionalString,
  requireArray,
  requireNumber,
  requireRecord,
  requireString,
  validationError,
  validationOk,
  type ValidationIssue,
  type ValidationResult,
} from "./common";

export namespace GeoJSON {
  export interface Polygon {
    type: "Polygon";
    coordinates: number[][][];
  }

  export interface MultiPolygon {
    type: "MultiPolygon";
    coordinates: number[][][][];
  }
}

export interface TimeSeriesPoint {
  date: string;
  value: number;
  quality?: string;
}

export interface EarthDailyRawInput {
  provider: "earthdaily";
  mode: "demo" | "live";
  field: {
    field_id: string;
    field_name: string;
    grower_id: string;
    farm_id: string;
    crop_type: string;
    crop_stage: string;
    acreage: number;
    geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
    timezone: string;
    region: string;
    soil_profile: {
      texture: string;
      awc_mm_per_m: number;
      rooting_depth_m: number;
      field_capacity: number;
      wilting_point: number;
    };
  };
  imagery: {
    stac_items: Array<{ id: string; collection: string; datetime: string; href: string }>;
    acquisition_date: string;
    cloud_cover: number;
    asset_links: Record<string, string>;
    index_maps: Record<string, string>;
    vegetation_indices: { ndvi_mean: number; ndre_mean: number; evi_mean: number; ndmi_mean: number };
    anomaly_layers: Array<{ id: string; type: string; severity: number; href: string }>;
  };
  time_series: {
    ndvi: TimeSeriesPoint[];
    ndmi: TimeSeriesPoint[];
    evi: TimeSeriesPoint[];
    ndre: TimeSeriesPoint[];
    lai: TimeSeriesPoint[];
    biomass: TimeSeriesPoint[];
    fapar: TimeSeriesPoint[];
    fcover: TimeSeriesPoint[];
  };
  weather: {
    forecast_days: number;
    precipitation: TimeSeriesPoint[];
    temperature_min: TimeSeriesPoint[];
    temperature_max: TimeSeriesPoint[];
    humidity: TimeSeriesPoint[];
    wind_speed: TimeSeriesPoint[];
    gdd: TimeSeriesPoint[];
    et0: TimeSeriesPoint[];
    et_forecast: TimeSeriesPoint[];
  };
  water_context: {
    soil_moisture_surface: number;
    soil_moisture_rootzone: number;
    estimated_depletion: number;
    water_stress_index: number;
    irrigation_history: Array<{ date: string; volume_mm: number; method: string }>;
    applied_water_actuals: Array<{ date: string; volume_mm: number }>;
  };
  agronomic_events: {
    emergence?: string;
    peak_growth?: string;
    senescence?: string;
    change_detection: Array<{ date: string; type: string; magnitude: number }>;
    hotspot_alerts: Array<{ date: string; type: string; severity: number; bbox: number[] }>;
  };
  metadata: {
    source: string;
    retrieved_at: string;
    data_freshness: string;
    missing_fields: string[];
    quality_flags: string[];
  };
}

const TIME_SERIES_KEYS = ["ndvi", "ndmi", "evi", "ndre", "lai", "biomass", "fapar", "fcover"] as const;
const WEATHER_SERIES_KEYS = [
  "precipitation",
  "temperature_min",
  "temperature_max",
  "humidity",
  "wind_speed",
  "gdd",
  "et0",
  "et_forecast",
] as const;

export class EarthDailyUnavailableError extends Error {
  constructor(message = "EarthDaily data is unavailable and demo fallback is disabled.") {
    super(message);
    this.name = "EarthDailyUnavailableError";
  }
}

export class EarthDailyLiveError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "EarthDailyLiveError";
    this.status = status;
  }
}

export function validateEarthDailyRawInput(value: unknown): ValidationResult<EarthDailyRawInput> {
  const issues: ValidationIssue[] = [];
  if (!isRecord(value)) {
    return validationError([{ path: "$", message: "Payload must be an object", code: "invalid_payload" }]);
  }

  if (hasInvalidNumber(value)) {
    issues.push({ path: "$", message: "Payload contains NaN or Infinity", code: "invalid_number" });
  }

  const provider = value.provider;
  if (provider !== "earthdaily") {
    issues.push({ path: "provider", message: "Unsupported provider", code: "unsupported_provider" });
  }
  if (value.mode !== "demo" && value.mode !== "live") {
    issues.push({ path: "mode", message: "mode must be demo or live", code: "invalid_mode" });
  }

  validateField(requireRecord(value, "field", "field", issues), issues);
  validateImagery(requireRecord(value, "imagery", "imagery", issues), issues);
  validateTimeSeries(requireRecord(value, "time_series", "time_series", issues), issues);
  validateWeather(requireRecord(value, "weather", "weather", issues), issues);
  validateWaterContext(requireRecord(value, "water_context", "water_context", issues), issues);
  validateAgronomicEvents(requireRecord(value, "agronomic_events", "agronomic_events", issues), issues);
  validateMetadata(requireRecord(value, "metadata", "metadata", issues), issues);

  return issues.length ? validationError(issues) : validationOk(value as unknown as EarthDailyRawInput);
}

function validateField(field: Record<string, unknown> | null, issues: ValidationIssue[]): void {
  if (!field) return;
  ["field_id", "field_name", "grower_id", "farm_id", "crop_type", "crop_stage", "timezone", "region"].forEach((key) =>
    requireString(field, key, `field.${key}`, issues)
  );
  requireNumber(field, "acreage", "field.acreage", issues);
  validateGeometry(field.geometry, issues);
  const soil = requireRecord(field, "soil_profile", "field.soil_profile", issues);
  if (!soil) return;
  requireString(soil, "texture", "field.soil_profile.texture", issues);
  ["awc_mm_per_m", "rooting_depth_m", "field_capacity", "wilting_point"].forEach((key) =>
    requireNumber(soil, key, `field.soil_profile.${key}`, issues)
  );
}

function validateGeometry(value: unknown, issues: ValidationIssue[]): void {
  if (!isRecord(value) || (value.type !== "Polygon" && value.type !== "MultiPolygon") || !Array.isArray(value.coordinates)) {
    issues.push({ path: "field.geometry", message: "geometry must be a Polygon or MultiPolygon", code: "invalid_geometry" });
  }
}

function validateImagery(imagery: Record<string, unknown> | null, issues: ValidationIssue[]): void {
  if (!imagery) return;
  validateObjectArray(imagery, "stac_items", "imagery.stac_items", ["id", "collection", "datetime", "href"], [], issues);
  requireString(imagery, "acquisition_date", "imagery.acquisition_date", issues);
  requireNumber(imagery, "cloud_cover", "imagery.cloud_cover", issues);
  validateStringRecord(imagery.asset_links, "imagery.asset_links", issues);
  validateStringRecord(imagery.index_maps, "imagery.index_maps", issues);
  const vi = requireRecord(imagery, "vegetation_indices", "imagery.vegetation_indices", issues);
  if (vi) {
    ["ndvi_mean", "ndre_mean", "evi_mean", "ndmi_mean"].forEach((key) =>
      requireNumber(vi, key, `imagery.vegetation_indices.${key}`, issues)
    );
  }
  validateObjectArray(imagery, "anomaly_layers", "imagery.anomaly_layers", ["id", "type", "href"], ["severity"], issues);
}

function validateTimeSeries(series: Record<string, unknown> | null, issues: ValidationIssue[]): void {
  if (!series) return;
  TIME_SERIES_KEYS.forEach((key) => validateTimeSeriesArray(series[key], `time_series.${key}`, issues));
}

function validateWeather(weather: Record<string, unknown> | null, issues: ValidationIssue[]): void {
  if (!weather) return;
  requireNumber(weather, "forecast_days", "weather.forecast_days", issues);
  WEATHER_SERIES_KEYS.forEach((key) => validateTimeSeriesArray(weather[key], `weather.${key}`, issues));
}

function validateWaterContext(water: Record<string, unknown> | null, issues: ValidationIssue[]): void {
  if (!water) return;
  ["soil_moisture_surface", "soil_moisture_rootzone", "estimated_depletion", "water_stress_index"].forEach((key) =>
    requireNumber(water, key, `water_context.${key}`, issues)
  );
  validateObjectArray(water, "irrigation_history", "water_context.irrigation_history", ["date", "method"], ["volume_mm"], issues);
  validateObjectArray(water, "applied_water_actuals", "water_context.applied_water_actuals", ["date"], ["volume_mm"], issues);
}

function validateAgronomicEvents(events: Record<string, unknown> | null, issues: ValidationIssue[]): void {
  if (!events) return;
  optionalString(events, "emergence", "agronomic_events.emergence", issues);
  optionalString(events, "peak_growth", "agronomic_events.peak_growth", issues);
  optionalString(events, "senescence", "agronomic_events.senescence", issues);
  validateObjectArray(events, "change_detection", "agronomic_events.change_detection", ["date", "type"], ["magnitude"], issues);
  const hotspots = requireArray(events, "hotspot_alerts", "agronomic_events.hotspot_alerts", issues);
  hotspots?.forEach((item, index) => {
    if (!isRecord(item)) {
      issues.push({ path: `agronomic_events.hotspot_alerts.${index}`, message: "Hotspot must be an object", code: "invalid_type" });
      return;
    }
    ["date", "type"].forEach((key) => requireString(item, key, `agronomic_events.hotspot_alerts.${index}.${key}`, issues));
    requireNumber(item, "severity", `agronomic_events.hotspot_alerts.${index}.severity`, issues);
    if (!Array.isArray(item.bbox) || item.bbox.some((n) => !isFiniteNumber(n))) {
      issues.push({ path: `agronomic_events.hotspot_alerts.${index}.bbox`, message: "bbox must be numeric", code: "invalid_number" });
    }
  });
}

function validateMetadata(metadata: Record<string, unknown> | null, issues: ValidationIssue[]): void {
  if (!metadata) return;
  ["source", "retrieved_at", "data_freshness"].forEach((key) => requireString(metadata, key, `metadata.${key}`, issues));
  validateStringArray(metadata.missing_fields, "metadata.missing_fields", issues);
  validateStringArray(metadata.quality_flags, "metadata.quality_flags", issues);
}

function validateTimeSeriesArray(value: unknown, path: string, issues: ValidationIssue[]): void {
  if (!Array.isArray(value)) {
    issues.push({ path, message: `${path} must be an array`, code: "missing_required" });
    return;
  }
  value.forEach((point, index) => {
    if (!isRecord(point)) {
      issues.push({ path: `${path}.${index}`, message: "Time series point must be an object", code: "invalid_type" });
      return;
    }
    requireString(point, "date", `${path}.${index}.date`, issues);
    requireNumber(point, "value", `${path}.${index}.value`, issues);
    optionalString(point, "quality", `${path}.${index}.quality`, issues);
  });
}

function validateObjectArray(
  parent: Record<string, unknown>,
  key: string,
  path: string,
  stringKeys: string[],
  numberKeys: string[],
  issues: ValidationIssue[],
): void {
  const rows = requireArray(parent, key, path, issues);
  rows?.forEach((row, index) => {
    if (!isRecord(row)) {
      issues.push({ path: `${path}.${index}`, message: "Entry must be an object", code: "invalid_type" });
      return;
    }
    stringKeys.forEach((field) => requireString(row, field, `${path}.${index}.${field}`, issues));
    numberKeys.forEach((field) => requireNumber(row, field, `${path}.${index}.${field}`, issues));
  });
}

function validateStringArray(value: unknown, path: string, issues: ValidationIssue[]): void {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    issues.push({ path, message: `${path} must be a string array`, code: "invalid_type" });
  }
}

function validateStringRecord(value: unknown, path: string, issues: ValidationIssue[]): void {
  if (!isRecord(value) || Object.values(value).some((item) => typeof item !== "string")) {
    issues.push({ path, message: `${path} must be a string record`, code: "invalid_type" });
  }
}
