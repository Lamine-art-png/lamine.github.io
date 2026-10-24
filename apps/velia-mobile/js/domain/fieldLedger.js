export const TERRIS_MODULES = Object.freeze(["water", "nutrients", "energy", "ops", "proof", "protect", "risk_api"]);

export const TERRIS_FIELD_EVENT_TYPES = Object.freeze([
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
]);

export const TERRIS_TRUTH_LABELS = Object.freeze(["measured", "reported", "calculated", "estimated", "ai_inferred", "unknown"]);
export const TERRIS_SOURCE_MODES = Object.freeze(["manual", "sensor", "controller", "backend", "local", "derived", "system", "demo", "offline", "voice"]);
export const TERRIS_DATA_QUALITY_LABELS = Object.freeze(["high", "medium", "low", "blocked", "unknown"]);

const validateOne = (value, allowed, label) => {
  if (!allowed.includes(value)) throw new Error(`Unsupported Terris ${label}: ${value}`);
};

export function safeRandomUuid() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `local-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

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
  const sourceMode = input.sourceMode || "manual";
  const truthLabel = input.truthLabel || "reported";
  const dataQuality = input.dataQuality || "unknown";
  validateOne(input.eventType, TERRIS_FIELD_EVENT_TYPES, "event type");
  validateOne(input.module, TERRIS_MODULES, "module");
  validateOne(sourceMode, TERRIS_SOURCE_MODES, "source mode");
  validateOne(truthLabel, TERRIS_TRUTH_LABELS, "truth label");
  validateOne(dataQuality, TERRIS_DATA_QUALITY_LABELS, "data quality");
  return {
    id: input.id || `event-${safeRandomUuid()}`,
    organizationId: input.organizationId || "local-org",
    workspaceId: input.workspaceId || "local-workspace",
    farmId: input.farmId || "local-farm",
    fieldId: input.fieldId,
    blockId: input.blockId || null,
    cropCycleId: input.cropCycleId || null,
    eventType: input.eventType,
    module: input.module,
    occurredAt: input.occurredAt || now,
    recordedAt: input.recordedAt || now,
    sourceMode,
    sourceSystem: input.sourceSystem || null,
    sourceRecordId: input.sourceRecordId || null,
    truthLabel,
    confidence: input.confidence,
    dataQuality,
    provenance: input.provenance || createProvenance(input),
    payload: input.payload || {},
    attachments: input.attachments || [],
    limitations: input.limitations || [],
    ledgerMetadata: {
      retentionLimit: input.retentionLimit || 500,
      persistenceMode: "local_mobile_buffer",
      durableBackendPersistence: false,
      queuedForSync: Boolean(input.queuedForSync),
    },
  };
}

export function appendLedgerEvent(state, event) {
  const retentionLimit = state.ledgerMetadata?.retentionLimit || event.ledgerMetadata?.retentionLimit || 500;
  return {
    ...state,
    ledgerMetadata: {
      retentionLimit,
      persistenceMode: "local_mobile_buffer",
      durableBackendPersistence: false,
      queuedForSync: Boolean(state.ledgerMetadata?.queuedForSync || event.ledgerMetadata?.queuedForSync),
    },
    fieldLedgerEvents: [event, ...(state.fieldLedgerEvents || [])].slice(0, retentionLimit),
  };
}

export function appendRecommendationEventIfNew(state, event) {
  const fingerprint = event?.payload?.fingerprint;
  const existing = fingerprint
    ? (state.fieldLedgerEvents || []).find((row) => row.eventType === "irrigation_recommendation" && row.payload?.fingerprint === fingerprint)
    : null;
  if (existing) return { state, appended: false };
  return { state: appendLedgerEvent(state, event), appended: true };
}

export function recommendationFingerprint({ fieldId, recommendation = {}, sourceMode, decisionVersion, occurredAt, decisionTraceRef }) {
  const occurredDate = occurredAt ? new Date(occurredAt).toISOString().slice(0, 10) : "";
  return [
    fieldId || "",
    recommendation.action || "",
    recommendation.urgency || "",
    recommendation.timing || "",
    sourceMode || recommendation.sourceMode || "",
    decisionVersion || recommendation.decisionVersion || occurredDate,
    decisionTraceRef || recommendation.decisionTrace?.id || recommendation.decisionTrace?.traceId || "",
  ].join("|");
}

export function waterRecommendationEvent({ field, recommendation, weather, fingerprint }) {
  return createTerrisFieldEvent({
    eventType: "irrigation_recommendation",
    module: "water",
    fieldId: field.id,
    sourceMode: TERRIS_SOURCE_MODES.includes(recommendation.sourceMode) ? recommendation.sourceMode : "derived",
    truthLabel: "ai_inferred",
    confidence: typeof recommendation.confidenceScore === "number" ? recommendation.confidenceScore : undefined,
    dataQuality: recommendation.missingData?.length ? "medium" : "high",
    payload: {
      action: recommendation.action,
      urgency: recommendation.urgency,
      timing: recommendation.timing,
      fingerprint,
      reasons: recommendation.reasons || [],
      missingData: recommendation.missingData || [],
      weatherSource: weather?.source || weather?.weatherSource || "local",
      decisionTraceRef: recommendation.decisionTrace?.id || recommendation.decisionTrace?.traceId || null,
    },
    limitations: recommendation.uncertainties || [],
  });
}

export function waterAppliedEvent(log) {
  return createTerrisFieldEvent({
    eventType: "irrigation_applied",
    module: "water",
    fieldId: log.fieldId,
    sourceMode: log.source === "controller" ? "controller" : log.source === "voice" ? "voice" : "manual",
    sourceRecordId: log.id,
    truthLabel: log.source === "controller" ? "measured" : "reported",
    occurredAt: log.performedAt,
    payload: {
      durationMin: log.durationMin,
      amountMm: log.amountMm,
      note: log.note || "",
      attachmentRefs: log.attachmentRefs || [],
      syncStatus: log.syncStatus || "local_pending",
    },
    attachments: log.attachmentRefs || [],
    queuedForSync: log.syncStatus === "local_pending",
  });
}

export function fieldObservationEvent(observation, module = "water") {
  return createTerrisFieldEvent({
    eventType: "field_observation",
    module,
    fieldId: observation.fieldId,
    sourceRecordId: observation.id,
    sourceMode: observation.source === "voice" ? "voice" : observation.source || "manual",
    truthLabel: "reported",
    occurredAt: observation.createdAt,
    payload: {
      condition: observation.condition,
      note: observation.note || "",
      attachmentRefs: observation.attachmentRefs || [],
      translation: observation.translation || null,
      geotag: observation.geotag || null,
      syncStatus: observation.syncStatus || "local_pending",
    },
    attachments: observation.attachmentRefs || [],
    queuedForSync: observation.syncStatus === "local_pending",
  });
}
