import { describe, expect, it } from "vitest";
import { buildDemoEarthDailyInput } from "../src/adapters/earthdaily/demoAdapter";
import { normalizeEarthDailyInput } from "../src/core/normalization/normalize";
import { evaluateRiskFlags } from "../src/core/risk/flags";
import type { NormalizedSignalPack } from "../src/schemas/signals";

function basePack(): NormalizedSignalPack {
  const pack = normalizeEarthDailyInput(buildDemoEarthDailyInput());
  pack.confidence_inputs.component_scores.moisture_stress_score = 0.1;
  pack.confidence_inputs.component_scores.et_pressure_score = 0.1;
  pack.confidence_inputs.component_scores.anomaly_severity = 0.1;
  pack.water_context.water_stress_index = 0.1;
  pack.water_context.estimated_depletion_mm = 5;
  pack.water_context.soil_moisture_rootzone = 0.2;
  pack.vegetation_context.ndmi_level = 0.35;
  pack.anomaly_context.max_anomaly_severity = 0.1;
  pack.anomaly_context.cloud_cover = 0.05;
  pack.data_quality.missing_fields = [];
  pack.data_quality.score = 0.95;
  pack.weather_context.series.temperature_max.forEach((point) => { point.value = 30; });
  return JSON.parse(JSON.stringify(pack)) as NormalizedSignalPack;
}

describe("risk flags", () => {
  it("is silent when triggers are below thresholds", () => {
    expect(Object.values(evaluateRiskFlags(basePack())).some(Boolean)).toBe(false);
  });

  it("fires each risk flag under trigger", () => {
    const cases: Array<[keyof ReturnType<typeof evaluateRiskFlags>, (pack: NormalizedSignalPack) => void]> = [
      ["water_stress", (pack) => { pack.water_context.water_stress_index = 0.7; }],
      ["heat_stress", (pack) => { pack.weather_context.series.temperature_max[0].value = 36; }],
      ["data_gap", (pack) => { pack.data_quality.missing_fields = ["ndmi"]; }],
      ["cloud_contamination", (pack) => { pack.anomaly_context.cloud_cover = 0.5; }],
      ["anomaly_detected", (pack) => { pack.anomaly_context.max_anomaly_severity = 0.6; }],
      ["over_irrigation_risk", (pack) => { pack.water_context.soil_moisture_rootzone = 0.29; pack.water_context.estimated_depletion_mm = 1; }],
      ["under_irrigation_risk", (pack) => { pack.water_context.estimated_depletion_mm = 70; }],
      ["sensor_conflict", (pack) => { pack.confidence_inputs.component_scores.moisture_stress_score = 0.75; pack.water_context.water_stress_index = 0.1; pack.vegetation_context.ndmi_level = 0.5; }],
    ];

    for (const [flag, mutate] of cases) {
      const pack = basePack();
      mutate(pack);
      expect(evaluateRiskFlags(pack)[flag]).toBe(true);
    }
  });
});

