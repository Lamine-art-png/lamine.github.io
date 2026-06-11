import { createTerrisFieldEvent } from "./fieldLedger.js";

export function createPumpAsset(input) {
  return {
    id: input.id || `pump-${Date.now()}`,
    farmId: input.farmId || "local-farm",
    fieldId: input.fieldId || null,
    blockId: input.blockId || null,
    ratedCapacity: input.ratedCapacity || null,
    energySource: input.energySource || "unknown",
    controllerId: input.controllerId || null,
    meterId: input.meterId || null,
    provenance: input.provenance || { source: "manual" },
    limitations: input.limitations || [],
  };
}

export function compareEligibleWindows({ recommendation, windows, tariff, mode = "real", pumpEvidence = null }) {
  if (mode !== "demo" && !pumpEvidence) return { status: "missing_pump_evidence", missingInputs: ["pump evidence"], windows: [], bestWindow: null };
  if (!tariff) return { status: "missing_tariff", missingInputs: ["tariff evidence"], windows: [], bestWindow: null };
  const eligible = (windows || []).filter((window) => window.allowedByWaterDecision !== false);
  const priced = eligible.map((window) => ({
    ...window,
    estimatedCost: Number(window.estimatedKwh || 0) * Number(window.energyRate ?? tariff.energyRate ?? 0),
    truthLabel: window.measuredKwh ? "measured" : "estimated",
    representativeDemo: mode === "demo" && Boolean(tariff.representativeDemo),
  }));
  priced.sort((a, b) => a.estimatedCost - b.estimatedCost);
  return {
    status: priced.length ? "ok" : "no_eligible_window",
    missingInputs: [],
    agronomicConstraint: recommendation?.timing || null,
    windows: priced,
    bestWindow: priced[0] || null,
    limitations: ["Cost optimization never overrides agronomic timing or field safety constraints."],
  };
}

export function demoEnergyComparison(recommendation) {
  return compareEligibleWindows({
    mode: "demo",
    recommendation,
    pumpEvidence: { representativeDemo: true },
    tariff: { energyRate: 0.24, representativeDemo: true },
    windows: [
      { label: "Representative off-peak evening", estimatedKwh: 30, energyRate: 0.24, allowedByWaterDecision: true },
      { label: "Representative unsafe midday", estimatedKwh: 28, energyRate: 0.14, allowedByWaterDecision: false },
    ],
  });
}

export function pumpingRuntimeEvent(input) {
  return createTerrisFieldEvent({
    eventType: input.estimatedCost != null ? "pumping_cost_estimate" : "pumping_runtime",
    module: "energy",
    fieldId: input.fieldId,
    sourceRecordId: input.id,
    sourceMode: input.sourceMode || "manual",
    truthLabel: input.measuredKwh != null || input.measuredCost != null ? "measured" : "estimated",
    occurredAt: input.timestamp || new Date().toISOString(),
    payload: input,
    limitations: input.limitations || [],
  });
}
