export function createField(input) {
  return {
    id: `field-${Date.now()}`,
    name: input.fieldName,
    crop: input.crop,
    acreage: Number(input.acreage),
    location: input.fieldLocation || "",
    coordinates: input.fieldCoordinates || input.coordinates || null,
    irrigationMethod: input.irrigationMethod,
    soilType: input.soilType || "",
    lastIrrigationAt: input.lastIrrigationAt || null,
    usualDurationMin: input.usualDurationMin ? Number(input.usualDurationMin) : null,
    waterSource: input.waterSource || "",
    dataSource: input.dataSource || "neither",
    dataSourceMode: input.dataSource || "neither",
    units: input.units || "metric",
    waterStressLevel: "moderate",
    lastObservation: null,
    verificationStatus: "needs field confirmation",
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
    attachmentRefs: payload.attachmentRefs || [],
    syncStatus: payload.syncStatus || (payload.offline ? "queued" : "synced"),
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
    attachmentRefs: payload.attachmentRefs || [],
    translation: payload.translation || null,
    geotag: payload.geotag || null,
    syncStatus: payload.syncStatus || (payload.offline ? "queued" : "synced"),
  };
}

export function createVoiceTimelineEntry(payload) {
  return {
    id: `voice-${Date.now()}`,
    transcript: payload.transcript,
    intent: payload.intent,
    outcome: payload.outcome,
    fieldId: payload.fieldId || null,
    attachmentRefs: payload.attachmentRefs || [],
    translation: payload.translation || null,
    syncStatus: payload.syncStatus || (payload.offline ? "queued" : "synced"),
    createdAt: new Date().toISOString(),
  };
}

export function createAttachmentMetadata(payload) {
  return {
    id: payload.id || `attachment-${Date.now()}`,
    type: payload.type || "photo",
    uri: payload.uri,
    fieldId: payload.fieldId || null,
    blockId: payload.blockId || null,
    cropCycleId: payload.cropCycleId || null,
    geotag: payload.geotag || null,
    translation: payload.translation || null,
    syncStatus: payload.syncStatus || "queued",
    offlineQueueState: payload.offlineQueueState || "queued",
    createdAt: payload.createdAt || new Date().toISOString(),
  };
}
