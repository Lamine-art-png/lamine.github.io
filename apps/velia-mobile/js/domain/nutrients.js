import { createTerrisFieldEvent } from "./fieldLedger.js";

export function createNutrientRecord(input) {
  const missingData = [];
  if (!input.waterVolume && input.concentration) missingData.push("water volume");
  if (input.waterVolume && !input.concentration) missingData.push("nutrient concentration");
  const canCalculate = Number.isFinite(Number(input.waterVolume)) && Number.isFinite(Number(input.concentration));
  return {
    id: input.id || `nutrient-${Date.now()}`,
    fieldId: input.fieldId,
    blockId: input.blockId || null,
    cropCycleId: input.cropCycleId || null,
    nutrientType: input.nutrientType,
    sourceType: input.sourceType || "manual",
    plannedQuantity: input.plannedQuantity ?? null,
    appliedQuantity: input.appliedQuantity ?? (canCalculate ? Number(input.waterVolume) * Number(input.concentration) : null),
    unit: input.unit || null,
    applicationMethod: input.applicationMethod || "unknown",
    timestamp: input.timestamp || new Date().toISOString(),
    linkedIrrigationEventId: input.linkedIrrigationEventId || null,
    provenance: input.provenance || { source: input.sourceType || "manual", assumptions: [], limitations: [] },
    truthLabel: input.appliedQuantity == null && canCalculate ? "calculated" : "reported",
    notes: input.notes || "",
    missingData,
    nextEvidenceRequired: missingData[0] || null,
    demo: Boolean(input.demo),
  };
}

export function nutrientLedgerEvent(record) {
  return createTerrisFieldEvent({
    eventType: record.applicationMethod === "fertigation" ? "fertigation_applied" : "nutrient_application",
    module: "nutrients",
    fieldId: record.fieldId,
    blockId: record.blockId,
    cropCycleId: record.cropCycleId,
    sourceRecordId: record.id,
    sourceMode: "manual",
    truthLabel: record.truthLabel,
    occurredAt: record.timestamp,
    dataQuality: record.missingData.length ? "blocked" : "medium",
    payload: record,
    limitations: record.missingData.length ? [`Withheld calculation until ${record.missingData.join(" and ")} is available.`] : [],
  });
}

export function plannedAppliedVariance(record) {
  if (!Number.isFinite(Number(record.plannedQuantity)) || !Number.isFinite(Number(record.appliedQuantity))) return null;
  return Number(record.appliedQuantity) - Number(record.plannedQuantity);
}
