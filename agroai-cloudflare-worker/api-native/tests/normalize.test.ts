import { describe, expect, it } from "vitest";
import { buildDemoEarthDailyInput } from "../src/adapters/earthdaily/demoAdapter";
import { normalizeEarthDailyInput } from "../src/core/normalization/normalize";

describe("normalization", () => {
  it("normalizes known demo input into expected score ranges", () => {
    const pack = normalizeEarthDailyInput(buildDemoEarthDailyInput());
    expect(pack.field_id).toBe("madera-almonds-block-12");
    expect(pack.weather_context.heat_days_7d).toBe(2);
    expect(pack.confidence_inputs.component_scores.moisture_stress_score).toBeCloseTo(0.34, 1);
    expect(pack.confidence_inputs.component_scores.data_quality_score).toBeGreaterThan(0.9);
    expect(pack.provider_trace.mode).toBe("demo");
  });
});
