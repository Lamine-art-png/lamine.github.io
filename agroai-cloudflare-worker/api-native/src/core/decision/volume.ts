import type { NormalizedSignalPack } from "../../schemas/signals";
import { clamp, round } from "../normalization/derive";
import {
  cropCoefficient,
  METHOD_APPLICATION_RATE_MM_PER_HOUR,
  METHOD_EFFICIENCY,
  METHOD_MAX_MM,
  normalizeKey,
} from "./rules";

const GALLONS_PER_ACRE_MM = 1069.0539;

export interface VolumeRecommendation {
  recommended_volume_mm: number;
  recommended_volume: number;
  recommended_volume_unit: "gallons_per_acre";
  estimated_duration: number;
  estimated_duration_unit: "hours";
  irrigation_method_assumption: string;
  kc_stage: number;
}

export function calculateRecommendedVolume(pack: NormalizedSignalPack): VolumeRecommendation {
  const method = normalizeMethod(pack.operational_context.irrigation_method_assumption);
  const kc = cropCoefficient(pack.crop_context.crop_type, pack.crop_context.crop_stage);
  const maxMethodMm = METHOD_MAX_MM[method];
  const netMm = clamp(
    pack.water_context.estimated_depletion_mm +
      pack.weather_context.et_forecast_7d_mm * kc -
      pack.weather_context.precipitation_7d_mm,
    0,
    maxMethodMm,
  );
  const grossGallonsPerAcre = (netMm * GALLONS_PER_ACRE_MM) / METHOD_EFFICIENCY[method];
  const duration = netMm / METHOD_APPLICATION_RATE_MM_PER_HOUR[method];

  return {
    recommended_volume_mm: round(netMm, 1),
    recommended_volume: Math.round(grossGallonsPerAcre),
    recommended_volume_unit: "gallons_per_acre",
    estimated_duration: round(duration, 1),
    estimated_duration_unit: "hours",
    irrigation_method_assumption: method,
    kc_stage: kc,
  };
}

function normalizeMethod(value: string): "drip" | "sprinkler" | "flood" {
  const method = normalizeKey(value);
  if (method.includes("sprinkler")) return "sprinkler";
  if (method.includes("flood")) return "flood";
  return "drip";
}

