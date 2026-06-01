import { describe, expect, it, beforeEach } from "vitest";
import { actions, getState, __resetForTest, SCENARIO_OPTIONS } from "../src/state/commandStore";

describe("commandStore", () => {
  beforeEach(() => __resetForTest());

  it("auto-loads the Alpha Vineyard representative decision", () => {
    const s = getState();
    expect(s.scenarioId).toBe("alpha-vineyard");
    expect(s.analysisMode).toBe("representative");
    expect(s.recommendationOrigin).toBe("representative_fallback");
    expect(s.entryState).toBe("entry");
    expect(s.decision.action).toMatch(/Irrigate 42 min tonight/);
    expect(s.analysisPhase).toBe("complete");
    expect(s.sources.length).toBe(7);
  });

  it("exposes the four workspace scenarios", () => {
    expect(SCENARIO_OPTIONS.map((o) => o.id)).toEqual([
      "alpha-vineyard",
      "almond-orchard",
      "multi-farm",
      "partner-validation",
    ]);
  });

  it("switches scenarios and updates the decision + reconciliation", () => {
    actions.switchScenario("almond-orchard");
    expect(getState().decision.crop).toBe("Almonds");
    expect(getState().decision.confidence).toBe("91%");

    actions.switchScenario("partner-validation");
    const s = getState();
    expect(s.decision.action).toMatch(/Validate partner feed/);
    expect(s.decision.estimatedWaterSavings).toBe("—");
    expect(s.reconciliation.some((r) => r.status === "Review")).toBe(true);
  });

  it("advances the evidence chain and stays truthful about origin", async () => {
    await actions.advanceEvidence("scheduled");
    await actions.advanceEvidence("applied");
    await actions.advanceEvidence("observed");
    await actions.advanceEvidence("verified");
    const evidence = getState().evidence;
    expect(evidence.every((step) => step.status === "Complete")).toBe(true);
    // Representative load must never claim a live/engine origin.
    expect(getState().recommendationOrigin).toBe("representative_fallback");
  });

  it("navigates between routes", () => {
    actions.navigate("integrations");
    expect(getState().route).toBe("integrations");
  });

  it("opens the evaluation workspace", async () => {
    await actions.openEvaluationWorkspace();
    expect(getState().entryState).toBe("workspace");
  });
});
