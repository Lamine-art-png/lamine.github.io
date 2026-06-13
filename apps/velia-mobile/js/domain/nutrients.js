import { createTerrisFieldEvent } from "./fieldLedger.js";

const finiteNumber = (value) => value !== "" && value !== null && value !== undefined && Number.isFinite(Number(value));

export function createNutrientRecord(input) {
  const missingData = [];
  if (!input.fieldId) missingData.push("field");
  if (!input.nutrientType) missingData.push("nutrient type");
  if (!input.sourceType) missingData.push("source type");
  if (!input.applicationMethod) missingData.push("application method");
  if (!input.unit) missingData.push("unit");
  if (!finiteNumber(input.waterVolume) && finiteNumber(input.concentration)) missingData.push("water volume");
  if (finiteNumber(input.waterVolume) && !finiteNumber(input.concentration)) missingData.push("nutrient concentration");
  const canCalculate = finiteNumber(input.waterVolume) && finiteNumber(input.concentration);
  const hasApplied = finiteNumber(input.appliedQuantity);
  const hasPlanned = finiteNumber(input.plannedQuantity);
  const hasQuantityEvidence = hasPlanned || hasApplied || canCalculate;
  if (!hasQuantityEvidence) missingData.push("quantity evidence");
  const appliedQuantity = hasApplied ? Number(input.appliedQuantity) : canCalculate ? Number(input.waterVolume) * Number(input.concentration) : null;
  const truthLabel = hasApplied ? "reported" : canCalculate ? "calculated" : "unknown";
  const hasRequiredMetadata = Boolean(input.fieldId && input.nutrientType && input.sourceType && input.applicationMethod && input.unit);
  const recordStatus = !hasRequiredMetadata || !hasQuantityEvidence
    ? "draft_missing_inputs"
    : appliedQuantity != null
      ? "applied"
      : "planned";
  return {
    id: input.id || `nutrient-${Date.now()}`,
    fieldId: input.fieldId || null,
    blockId: input.blockId || null,
    cropCycleId: input.cropCycleId || null,
    nutrientType: input.nutrientType || "",
    sourceType: input.sourceType || "",
    plannedQuantity: finiteNumber(input.plannedQuantity) ? Number(input.plannedQuantity) : null,
    appliedQuantity,
    unit: input.unit || null,
    applicationMethod: input.applicationMethod || "",
    waterVolume: finiteNumber(input.waterVolume) ? Number(input.waterVolume) : null,
    concentration: finiteNumber(input.concentration) ? Number(input.concentration) : null,
    timestamp: input.timestamp || new Date().toISOString(),
    linkedIrrigationEventId: input.linkedIrrigationEventId || null,
    provenance: input.provenance || { source: "manual", assumptions: [], limitations: [] },
    truthLabel,
    recordStatus,
    notes: input.notes || "",
    missingData,
    nextEvidenceRequired: missingData[0] || null,
    demo: Boolean(input.demo),
    representativeDemo: Boolean(input.representativeDemo || input.demo),
    syncStatus: input.syncStatus || (input.offline ? "queued" : "synced"),
  };
}

export function nutrientLedgerEvent(record) {
  const eventType = record.applicationMethod === "fertigation"
    ? record.appliedQuantity != null ? "fertigation_applied" : "fertigation_plan"
    : "nutrient_application";
  return createTerrisFieldEvent({
    eventType,
    module: "nutrients",
    fieldId: record.fieldId,
    blockId: record.blockId,
    cropCycleId: record.cropCycleId,
    sourceRecordId: record.id,
    sourceMode: record.representativeDemo ? "demo" : "manual",
    truthLabel: record.truthLabel,
    occurredAt: record.timestamp,
    dataQuality: record.recordStatus === "draft_missing_inputs" || record.missingData.length ? "blocked" : "medium",
    payload: { ...record, recordStatus: record.recordStatus, syncStatus: record.syncStatus || "synced" },
    limitations: record.missingData.length ? [`Withheld calculation until ${record.missingData.join(" and ")} is available.`] : [],
    queuedForSync: record.syncStatus === "queued",
  });
}

export function plannedAppliedVariance(record) {
  if (!finiteNumber(record.plannedQuantity) || !finiteNumber(record.appliedQuantity)) return null;
  return Number(record.appliedQuantity) - Number(record.plannedQuantity);
}
