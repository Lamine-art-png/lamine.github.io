import { describe, expect, it } from "vitest";
import { buildDemoEarthDailyInput } from "../src/adapters/earthdaily/demoAdapter";
import { scoreConfidence, confidenceLevel } from "../src/core/confidence/score";
import { normalizeEarthDailyInput } from "../src/core/normalization/normalize";
import { evaluateRiskFlags } from "../src/core/risk/flags";

describe("confidence", () => {
  it("maps score boundaries to levels", () => {
    expect(confidenceLevel(0.44)).toBe("low");
    expect(confidenceLevel(0.69)).toBe("medium");
    expect(confidenceLevel(0.84)).toBe("high");
    expect(confidenceLevel(0.85)).toBe("very_high");
  });

  it("selects drivers and limitations", () => {
    const pack = normalizeEarthDailyInput(buildDemoEarthDailyInput());
    const confidence = scoreConfidence(pack, evaluateRiskFlags(pack));
    expect(confidence.drivers).toHaveLength(3);
    expect(confidence.limitations.length).toBeGreaterThan(0);
    expect(confidence.score).toBeGreaterThan(0);
  });
});

