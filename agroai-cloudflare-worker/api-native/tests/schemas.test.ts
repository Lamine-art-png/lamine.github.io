import { describe, expect, it } from "vitest";
import { buildDemoEarthDailyInput } from "../src/adapters/earthdaily/demoAdapter";
import { validateEarthDailyRawInput } from "../src/schemas/earthdaily";

describe("EarthDaily schemas", () => {
  it("rejects missing required fields", () => {
    const input = buildDemoEarthDailyInput() as Record<string, unknown>;
    delete input.field;
    const result = validateEarthDailyRawInput(input);
    expect(result.ok).toBe(false);
    expect(result.issues.some((issue) => issue.code === "missing_required")).toBe(true);
  });

  it("rejects an unsupported provider", () => {
    const input = { ...buildDemoEarthDailyInput(), provider: "other" };
    const result = validateEarthDailyRawInput(input);
    expect(result.ok).toBe(false);
    expect(result.issues[0].code).toBe("unsupported_provider");
  });

  it("rejects NaN and Infinity", () => {
    const input = buildDemoEarthDailyInput();
    input.field.acreage = Number.NaN;
    input.water_context.estimated_depletion = Number.POSITIVE_INFINITY;
    const result = validateEarthDailyRawInput(input);
    expect(result.ok).toBe(false);
    expect(result.issues.some((issue) => issue.code === "invalid_number")).toBe(true);
  });
});

