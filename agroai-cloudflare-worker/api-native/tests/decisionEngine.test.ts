import { describe, expect, it } from "vitest";
import { buildDemoEarthDailyInput } from "../src/adapters/earthdaily/demoAdapter";
import { runDecisionEngine } from "../src/core/decision/engine";
import { normalizeEarthDailyInput } from "../src/core/normalization/normalize";
import type { NormalizedSignalPack } from "../src/schemas/signals";

function pack(): NormalizedSignalPack {
  return JSON.parse(JSON.stringify(normalizeEarthDailyInput(buildDemoEarthDailyInput()))) as NormalizedSignalPack;
}

function decide(p: NormalizedSignalPack) {
  return runDecisionEngine({ signalPack: p, inputHash: "hash" }).recommendation.action;
}

describe("decision engine", () => {
  it("selects irrigate", () => {
    const p = pack();
    p.confidence_inputs.component_scores.priority_score = 0.72;
    p.confidence_inputs.component_scores.moisture_stress_score = 0.68;
    p.confidence_inputs.component_scores.data_quality_score = 0.95;
    p.water_context.water_stress_index = 0.65;
    p.water_context.soil_moisture_rootzone = 0.2;
    expect(decide(p)).toBe("irrigate");
  });

  it("selects wait", () => {
    const p = pack();
    p.confidence_inputs.component_scores.priority_score = 0.12;
    p.confidence_inputs.component_scores.moisture_stress_score = 0.12;
    p.water_context.water_stress_index = 0.12;
    p.vegetation_context.ndmi_level = 0.5;
    expect(decide(p)).toBe("wait");
  });

  it("selects monitor", () => {
    const p = pack();
    p.confidence_inputs.component_scores.priority_score = 0.38;
    p.confidence_inputs.component_scores.moisture_stress_score = 0.35;
    expect(decide(p)).toBe("monitor");
  });

  it("selects investigate", () => {
    const p = pack();
    p.confidence_inputs.component_scores.data_quality_score = 0.2;
    p.data_quality.score = 0.2;
    expect(decide(p)).toBe("investigate");
  });

  it("selects manual_review", () => {
    const p = pack();
    p.confidence_inputs.component_scores.priority_score = 0.18;
    p.confidence_inputs.component_scores.moisture_stress_score = 0.7;
    p.confidence_inputs.component_scores.data_quality_score = 0.95;
    p.water_context.water_stress_index = 0.1;
    p.vegetation_context.ndmi_level = 0.5;
    expect(decide(p)).toBe("manual_review");
  });
});

