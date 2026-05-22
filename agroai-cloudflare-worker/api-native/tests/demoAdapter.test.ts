import { describe, expect, it } from "vitest";
import { buildDemoEarthDailyInput } from "../src/adapters/earthdaily/demoAdapter";

describe("demo adapter", () => {
  it("builds an internally consistent demo payload", () => {
    const input = buildDemoEarthDailyInput();
    expect(input.provider).toBe("earthdaily");
    expect(input.mode).toBe("demo");
    expect(input.metadata.source).toBe("agroai-demo-fixture");
    expect(input.time_series.ndvi).toHaveLength(30);
    expect(input.weather.temperature_max).toHaveLength(7);
    expect(input.weather.temperature_max.some((point) => point.value >= 35)).toBe(true);
    expect(input.agronomic_events.hotspot_alerts).toHaveLength(1);
    expect(input.time_series.ndvi[0].date < input.time_series.ndvi.at(-1)!.date).toBe(true);
    expect(input.imagery.vegetation_indices.ndvi_mean).toBeGreaterThan(0);
    expect(input.imagery.vegetation_indices.ndvi_mean).toBeLessThan(1);
  });
});

