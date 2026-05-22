import { describe, expect, it } from "vitest";
import { buildDemoEarthDailyInput } from "../src/adapters/earthdaily/demoAdapter";
import { runDecisionEngine } from "../src/core/decision/engine";
import { normalizeEarthDailyInput } from "../src/core/normalization/normalize";
import { buildReportObject } from "../src/core/reporting/report";

describe("report assembly", () => {
  it("assembles with deterministic fallback when LLM is unavailable", async () => {
    const pack = normalizeEarthDailyInput(buildDemoEarthDailyInput());
    const decision = runDecisionEngine({ signalPack: pack, inputHash: "hash" });
    const result = await buildReportObject(decision, pack, {});
    expect(result.ai_review.fallback_used).toBe(true);
    expect(result.report_object.decision_id).toBe(decision.decision_id);
    expect(result.report_object.pdf_ready_sections.executive_summary).toContain("AGRO-AI");
  });
});

