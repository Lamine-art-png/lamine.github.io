import type { EarthDailyRawInput, TimeSeriesPoint } from "./earthdaily";

export interface ComponentScores {
  moisture_stress_score: number;
  et_pressure_score: number;
  vegetation_stress_score: number;
  anomaly_severity: number;
  weather_risk_score: number;
  data_quality_score: number;
  priority_score: number;
}

export interface NormalizedSignalPack {
  signal_pack_id: string;
  field_id: string;
  crop_context: {
    crop_type: string;
    crop_stage: string;
    acreage: number;
    region: string;
    timezone: string;
  };
  spatial_context: {
    geometry: EarthDailyRawInput["field"]["geometry"];
    field_name: string;
    grower_id: string;
    farm_id: string;
  };
  weather_context: {
    forecast_days: number;
    precipitation_7d_mm: number;
    et0_7d_mm: number;
    et_forecast_7d_mm: number;
    heat_days_7d: number;
    max_wind_speed_7d: number;
    series: EarthDailyRawInput["weather"];
  };
  water_context: {
    soil_moisture_surface: number;
    soil_moisture_rootzone: number;
    estimated_depletion_mm: number;
    water_stress_index: number;
    plant_available_water_mm: number;
    irrigation_history: EarthDailyRawInput["water_context"]["irrigation_history"];
    applied_water_actuals: EarthDailyRawInput["water_context"]["applied_water_actuals"];
  };
  vegetation_context: {
    indices: EarthDailyRawInput["imagery"]["vegetation_indices"];
    ndvi_14d_slope: number;
    ndre_14d_slope: number;
    ndmi_level: number;
    latest_series: Record<string, TimeSeriesPoint | null>;
  };
  anomaly_context: {
    cloud_cover: number;
    anomaly_layers: EarthDailyRawInput["imagery"]["anomaly_layers"];
    hotspot_alerts: EarthDailyRawInput["agronomic_events"]["hotspot_alerts"];
    change_detection: EarthDailyRawInput["agronomic_events"]["change_detection"];
    max_anomaly_severity: number;
  };
  operational_context: {
    irrigation_method_assumption: string;
    acquisition_date: string;
    retrieved_at: string;
    data_freshness_hours: number;
  };
  data_quality: {
    missing_fields: string[];
    quality_flags: string[];
    cloud_cover: number;
    freshness_hours: number;
    score: number;
  };
  confidence_inputs: {
    component_scores: ComponentScores;
    signal_agreement: number;
    recency_score: number;
    model_self_consistency: number;
  };
  provider_trace: {
    provider: "earthdaily";
    mode: "demo" | "live";
    source: string;
    stac_item_count: number;
    asset_links: Record<string, string>;
    index_maps: Record<string, string>;
  };
}

export function isNormalizedSignalPack(value: unknown): value is NormalizedSignalPack {
  return typeof value === "object" && value !== null && (value as NormalizedSignalPack).signal_pack_id !== undefined;
}

