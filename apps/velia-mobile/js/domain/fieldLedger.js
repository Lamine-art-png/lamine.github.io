export const terrisModules = ["water", "nutrients", "energy", "ops", "proof", "protect", "risk_api"];

export const terrisFieldEventTypes = [
  "irrigation_recommendation",
  "irrigation_approval",
  "irrigation_schedule",
  "irrigation_applied",
  "irrigation_verified",
  "fertigation_plan",
  "fertigation_applied",
  "nutrient_application",
  "pumping_runtime",
  "pumping_cost_estimate",
  "field_observation",
  "anomaly_detected",
  "crop_protection_task",
  "task_created",
  "task_completed",
  "evidence_attached",
  "evidence_packet_generated",
  "outcome_recorded",
];

export function createProvenance(input = {}) {
  return {
    actorId: input.actorId || null,
    actorType: input.actorType || "user",
    recordedBy: input.recordedBy || "terris-mobile",
    source: input.source || "manual",
    sourceTimestamp: input.sourceTimestamp || input.timestamp || new Date().toISOString(),
    assumptions: input.assumptions || [],
    limitations: input.limitations || [],
  };
}

export function createTerrisFieldEvent(input) {
  const now = new Date().toISOString();
  if (!terrisFieldEventTypes.includes(input.eventType)) throw new Error(`Unsupported Terris event type: ${input.eventType}`);
  if (!terrisModules.includes(input.module)) throw new Error(`Unsupported Terris module: ${input.module}`);
  return {
    id: input.id || `event-${Date.now()}-${Math.floor(Math.random() * 10000)}`,
    organizationId: input.organizationId || "local-org",
    workspaceId: input.workspaceId || "local-workspace",
    farmId: input.farmId || "local-farm",
    fieldId: input.fieldId,
    blockId: input.blockId,
    cropCycleId: input.cropCycleId,
    eventType: input.eventType,
    module: input.module,
    occurredAt: input.occurredAt || now,
    recordedAt: input.recordedAt || now,
    sourceMode: input.sourceMode || "manual",
    sourceSystem: input.sourceSystem,
    sourceRecordId: input.sourceRecordId,
    truthLabel: input.truthLabel || "reported",
    confidence: input.confidence,
    dataQuality: input.dataQuality || "medium",
    provenance: input.provenance || createProvenance(input),
    payload: input.payload || {},
    attachments: input.attachments || [],
    limitations: input.limitations || [],
  };
}

export function appendLedgerEvent(state, event) {
  return {
    ...state,
    fieldLedgerEvents: [event, ...(state.fieldLedgerEvents || [])].slice(0, 500),
  };
}

export function waterRecommendationEvent({ field, recommendation, weather }) {
  return createTerrisFieldEvent({
    eventType: "irrigation_recommendation",
    module: "water",
    fieldId: field.id,
    sourceMode: "derived",
    truthLabel: "ai_inferred",
    confidence: typeof recommendation.confidenceScore === "number" ? recommendation.confidenceScore : undefined,
    dataQuality: recommendation.missingData?.length ? "medium" : "high",
    payload: {
      action: recommendation.action,
      urgency: recommendation.urgency,
      timing: recommendation.timing,
      reasons: recommendation.reasons || [],
      missingData: recommendation.missingData || [],
      weatherSource: weather?.source || weather?.weatherSource || "local",
    },
    limitations: recommendation.uncertainties || [],
  });
}

export function waterAppliedEvent(log) {
  return createTerrisFieldEvent({
    eventType: "irrigation_applied",
    module: "water",
    fieldId: log.fieldId,
    sourceMode: log.source === "voice" ? "manual" : log.source || "manual",
    sourceRecordId: log.id,
    truthLabel: log.source === "controller" ? "measured" : "reported",
    occurredAt: log.performedAt,
    payload: {
      durationMin: log.durationMin,
      amountMm: log.amountMm,
      note: log.note || "",
    },
  });
}

export function fieldObservationEvent(observation, module = "water") {
  return createTerrisFieldEvent({
    eventType: "field_observation",
    module,
    fieldId: observation.fieldId,
    sourceRecordId: observation.id,
    sourceMode: observation.source === "voice" ? "manual" : observation.source || "manual",
    truthLabel: "reported",
    occurredAt: observation.createdAt,
    payload: {
      condition: observation.condition,
      note: observation.note || "",
    },
  });
}
