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
  const appliedQuantity = hasApplied ? Number(input.appliedQuantity) : canCalculate ? Number(input.waterVolume) * Number(input.concentration) : null;
  const truthLabel = hasApplied ? "reported" : canCalculate ? "calculated" : "unknown";
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
    truthLabel: record.truthLabel === "unknown" ? "reported" : record.truthLabel,
    occurredAt: record.timestamp,
    dataQuality: record.missingData.length ? "blocked" : "medium",
    payload: record,
    limitations: record.missingData.length ? [`Withheld calculation until ${record.missingData.join(" and ")} is available.`] : [],
  });
}

export function plannedAppliedVariance(record) {
  if (!finiteNumber(record.plannedQuantity) || !finiteNumber(record.appliedQuantity)) return null;
  return Number(record.appliedQuantity) - Number(record.plannedQuantity);
}
