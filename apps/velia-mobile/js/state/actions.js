export function createField(input) {
  return {
    id: `field-${Date.now()}`,
    name: input.fieldName,
    crop: input.crop,
    acreage: Number(input.acreage),
    irrigationMethod: input.irrigationMethod,
    soilType: input.soilType || "",
    lastIrrigationAt: input.lastIrrigationAt || null,
    usualDurationMin: input.usualDurationMin ? Number(input.usualDurationMin) : null,
    waterSource: input.waterSource || "",
    dataSource: input.dataSource || "neither",
    waterStressLevel: "moderate",
    lastObservation: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

export function createIrrigationLog(payload) {
  return {
    id: `log-${Date.now()}`,
    fieldId: payload.fieldId,
    durationMin: Number(payload.durationMin),
    amountMm: payload.amountMm ? Number(payload.amountMm) : null,
    note: payload.note || "",
    source: payload.source || "manual",
    performedAt: payload.performedAt || new Date().toISOString(),
  };
}

export function createObservation(payload) {
  return {
    id: `obs-${Date.now()}`,
    fieldId: payload.fieldId,
    condition: payload.condition,
    note: payload.note || "",
    source: payload.source || "manual",
    createdAt: new Date().toISOString(),
  };
}
