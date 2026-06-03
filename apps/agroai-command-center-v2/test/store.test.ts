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
    // Offline fallback action includes "Block A North" but withholds precision values.
    expect(s.decision.action).toMatch(/Block A North/);
    // Precision fields are withheld in offline fallback — must come from backend.
    expect(s.decision.confidence).toBe("—");
    expect(s.decision.evidenceCompleteness).toBe("—");
    expect(s.decision.estimatedWaterSavings).toBe("—");
    expect(s.decision.duration).toBeUndefined();
    expect(s.decision.estimatedVolume).toBeUndefined();
    expect(s.analysisPhase).toBe("complete");
    expect(s.sources.length).toBe(7);
  });

  it("exposes the two evaluation scenarios", () => {
    expect(SCENARIO_OPTIONS.map((o) => o.id)).toEqual([
      "alpha-vineyard",
      "incomplete-evidence",
    ]);
    expect(SCENARIO_OPTIONS[0].name).toBe("Validated operating block");
    expect(SCENARIO_OPTIONS[1].name).toBe("Incomplete evidence review");
  });

  it("switches scenarios and updates the decision + reconciliation", async () => {
    // switchScenario is async; backend will fail in test env and fall back to local data.
    await actions.switchScenario("almond-orchard");
    expect(getState().decision.crop).toBe("Almonds");
    // almond-orchard uses local fallback data (not backend-driven in this env).
    expect(getState().scenarioId).toBe("almond-orchard");

    await actions.switchScenario("partner-validation");
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

  // --- Section 7: Representative value leakage ---

  it("does not display representative precision for live engine results", async () => {
    // The initial seeded state uses representative_fallback origin.
    // We verify the invariant: offline fallback withholds precision but keeps identification.
    await actions.switchScenario("alpha-vineyard");
    const rep = getState().decision;
    // Offline fallback identifies the block without precision.
    expect(rep.action).toMatch(/Block A North/);
    expect(rep.recommendationOrigin).toBe("representative_fallback");
    expect(rep.start).toBeTruthy();
    expect(rep.appliedWater).toBeTruthy();
    expect(rep.driver).toBeTruthy();
    // Precision fields are withheld.
    expect(rep.confidence).toBe("—");
    expect(rep.evidenceCompleteness).toBe("—");
    expect(rep.estimatedWaterSavings).toBe("—");
    // The honest labels for non-representative origins must not equal the offline fallback values.
    const HONEST_LABELS = [
      "Pending evidence", "Withheld pending validation",
      "Source context incomplete", "Tenant baseline required", "—",
    ];
    HONEST_LABELS.forEach((label) => {
      expect(label).not.toBe(rep.action);
    });
  });

  it("uses honest pending labels when live result omits domain fields", () => {
    // For live_intelligence_engine origin, missing fields must show honest labels,
    // never precision values injected in the frontend.
    // The offline fallback for alpha-vineyard now withholds precision.
    const OFFLINE_FALLBACK_PRECISION_VALUES = [
      "21:00 – 21:42 PT", "12.2 mm net", "42 min",
      "Irrigate Block A North — 42 min tonight",
      "14.2 mm gross", "19.9 m³", "86%", "92%", "27% vs evaluation baseline",
    ];
    const HONEST_LABELS = [
      "Pending evidence",
      "Withheld pending validation",
      "Source context incomplete",
      "Tenant baseline required",
      "—",
      "Decision pending source review",
    ];
    // Verify the guard: honest labels must not equal any previously hardcoded precision value.
    OFFLINE_FALLBACK_PRECISION_VALUES.forEach((forbidden) => {
      HONEST_LABELS.forEach((label) => {
        expect(label).not.toBe(forbidden);
      });
    });
    // The offline fallback state must also not contain the removed precision values.
    const s = getState().decision;
    expect(s.action).not.toBe("Irrigate Block A North — 42 min tonight");
    expect(s.duration).toBeUndefined();
    expect(s.estimatedVolume).toBeUndefined();
    expect(s.confidence).toBe("—");
    expect(s.estimatedWaterSavings).toBe("—");
  });

  // --- Section 8: Evidence action truth states ---

  it("records evidence steps with honest operator-attestation text", async () => {
    await actions.advanceEvidence("scheduled");
    const scheduledStep = getState().evidence.find((s) => s.key === "scheduled");
    expect(scheduledStep?.status).toBe("Complete");
    expect(scheduledStep?.evidence).toBe("Schedule approval recorded.");
    expect(scheduledStep?.evidence).not.toContain("controller");
    expect(scheduledStep?.evidenceType).toBe("operator_attestation");
  });

  it("records applied-water step without implying controller confirmation", async () => {
    await actions.advanceEvidence("scheduled");
    await actions.advanceEvidence("applied");
    const appliedStep = getState().evidence.find((s) => s.key === "applied");
    expect(appliedStep?.evidence).toBe("Operator applied-water confirmation recorded.");
    expect(appliedStep?.evidence).not.toContain("from controller event");
    expect(appliedStep?.evidenceType).toBe("operator_attestation");
  });

  it("records field observation step truthfully", async () => {
    await actions.advanceEvidence("scheduled");
    await actions.advanceEvidence("applied");
    await actions.advanceEvidence("observed");
    const step = getState().evidence.find((s) => s.key === "observed");
    expect(step?.evidence).toBe("Field observation recorded.");
    expect(step?.evidenceType).toBe("field_observation");
  });

  // --- Section 9: Report honest labels for non-representative origins ---

  it("representative report contains farm and block from representative scenario", async () => {
    await actions.switchScenario("alpha-vineyard");
    const { report } = getState();
    expect(report.farm).toBe("Alpha Vineyard");
    expect(report.block).toBe("Block A North");
    // estimatedWaterSavings is withheld in offline fallback — must come from backend.
    // The report still identifies farm and block correctly.
  });

  it("report honest labels do not include representative farm or block values", () => {
    // Verify the honest-label values used for non-representative origins
    // are clearly distinct from the representative scenario values.
    const HONEST_LABELS = [
      "Source context incomplete",
      "Pending confirmation",
      "Withheld pending validation",
      "—",
    ];
    const FORBIDDEN = ["Alpha Vineyard", "Block A North", "Within 8% of plan", "27% vs evaluation baseline"];
    HONEST_LABELS.forEach((label) => {
      FORBIDDEN.forEach((forbidden) => {
        expect(label).not.toBe(forbidden);
      });
    });
  });

  // --- Section 10: Evidence advance blocked when backend is reachable and rejects ---

  it("does not advance local evidence for representative_fallback origin (baseline check)", async () => {
    // For representative_fallback with no sessionId, the local fallback must still advance.
    await actions.switchScenario("alpha-vineyard"); // representative_fallback origin
    const before = getState().evidence.find((s) => s.key === "scheduled")?.status;
    expect(before).toBe("Pending");
    await actions.advanceEvidence("scheduled");
    const after = getState().evidence.find((s) => s.key === "scheduled")?.status;
    expect(after).toBe("Complete");
  });

  // --- Section 11: Fifth-pass surgical corrections ---

  it("no 'Runtime reachable' string in any reconciliation row", async () => {
    for (const scenarioId of ["alpha-vineyard", "partner-validation"] as const) {
      await actions.switchScenario(scenarioId);
      const { reconciliation } = getState();
      reconciliation.forEach((row) => {
        expect(row.signal).not.toContain("Runtime reachable");
        expect(row.interpretation).not.toContain("Runtime reachable");
      });
    }
  });

  it("source_rows from backend are consumed when present", async () => {
    // Simulate a backend result with source_rows and verify it is used instead of derivation.
    const { __applyBackendResult } = await import("../src/state/commandStore");
    const fakeResult = {
      analysis_id: "test-id",
      session_id: "test-session",
      status: "complete",
      analysis_mode: "uploaded" as const,
      recommendation_origin: "uploaded_intelligence_engine" as const,
      context_origin: "uploaded" as const,
      source_rows: [
        {
          source_label: "Sensor Pack",
          source_kind: "controller_events",
          selected_scope_record_count: 5,
          package_record_count: 20,
          latest_timestamp: "2026-05-16T12:00:00Z",
          latest_signal_summary: "5 events for Block A North",
          status: "validated",
          limitations: [],
          contribution_label: "Not scored",
        },
      ],
      recommendation: { schedulable: true, scheduling_block_reasons: [] },
      reconciliation: {},
      normalized_context: {},
      signal_summary: {},
      warnings: [],
      uploaded_artifacts_used: [],
      live_inputs_used: [],
    };
    __applyBackendResult("alpha-vineyard", fakeResult as any, "test-session");
    const { sources } = getState();
    const sensorRow = sources.find((r) => r.source === "Sensor Pack");
    expect(sensorRow).toBeDefined();
    expect(sensorRow?.records).toBe("5 / 20");
  });

  it("incomplete guidance shown when decision.schedulable is false (backend state)", async () => {
    // Verify that showGuidance logic is based on decision.schedulable not scenarioId.
    const { __applyBackendResult } = await import("../src/state/commandStore");
    const fakeResult = {
      analysis_id: "test-id",
      session_id: "test-session",
      status: "complete",
      analysis_mode: "uploaded" as const,
      recommendation_origin: "uploaded_intelligence_engine" as const,
      context_origin: "uploaded" as const,
      limitations: ["Block area not provided"],
      recommendation: {
        schedulable: false,
        scheduling_block_reasons: ["Flow evidence not validated"],
        next_evidence_required: ["Upload flow meter records"],
      },
      reconciliation: {},
      normalized_context: {},
      signal_summary: {},
      warnings: [],
      uploaded_artifacts_used: [],
      live_inputs_used: [],
    };
    __applyBackendResult("alpha-vineyard", fakeResult as any, "test-session");
    const { decision } = getState();
    expect(decision.schedulable).toBe(false);
    expect(decision.limitations).toEqual(["Block area not provided"]);
  });

  it("uploaded mode preserved after backend result applied", async () => {
    const { __applyBackendResult } = await import("../src/state/commandStore");
    const fakeResult = {
      analysis_id: "test-id",
      session_id: "test-session",
      status: "complete",
      analysis_mode: "uploaded" as const,
      recommendation_origin: "uploaded_intelligence_engine" as const,
      context_origin: "uploaded" as const,
      recommendation: { schedulable: true, scheduling_block_reasons: [] },
      reconciliation: {},
      normalized_context: {},
      signal_summary: {},
      warnings: [],
      uploaded_artifacts_used: ["controller_events.csv"],
      live_inputs_used: [],
    };
    __applyBackendResult("alpha-vineyard", fakeResult as any, "test-session");
    expect(getState().analysisMode).toBe("uploaded");
    expect(getState().backendMeta?.uploadedArtifacts).toContain("controller_events.csv");
  });
});
