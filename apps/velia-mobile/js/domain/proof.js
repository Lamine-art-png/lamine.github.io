import { createTerrisFieldEvent } from "./fieldLedger.js";

export const TERRIS_PROOF_DISCLAIMER = "Evidence packets are operational records generated from available data. They are not official regulatory filings. They are not legal advice. Estimated and calculated values remain labeled.";

export function createEvidenceArtifact(input) {
  return {
    id: input.id || `artifact-${Date.now()}`,
    linkedEventId: input.linkedEventId,
    fieldId: input.fieldId,
    blockId: input.blockId || null,
    cropCycleId: input.cropCycleId || null,
    artifactType: input.artifactType,
    sourceMode: input.sourceMode || "manual",
    truthLabel: input.truthLabel || "reported",
    provenance: input.provenance || { source: "manual" },
    timestamp: input.timestamp || new Date().toISOString(),
    attachmentRef: input.attachmentRef || null,
    limitations: input.limitations || [],
    auditRef: input.auditRef || null,
  };
}

export function filterEvidenceEvents(events = [], scope = {}) {
  const start = scope.dateWindow?.start ? new Date(`${scope.dateWindow.start}T00:00:00.000Z`).getTime() : null;
  const end = scope.dateWindow?.end ? new Date(`${scope.dateWindow.end}T23:59:59.999Z`).getTime() : null;
  return events.filter((event) => {
    if (scope.moduleScope && event.module !== scope.moduleScope) return false;
    if (scope.farmScope && event.farmId !== scope.farmScope) return false;
    if (scope.fieldScope && event.fieldId !== scope.fieldScope) return false;
    if (scope.blockScope && event.blockId !== scope.blockScope) return false;
    const occurred = new Date(event.occurredAt || event.recordedAt || 0).getTime();
    if (start != null && occurred < start) return false;
    if (end != null && occurred > end) return false;
    return true;
  });
}

export function reviewRowsForEvents(events = []) {
  return events.map((event) => ({
    id: event.id,
    eventType: event.eventType,
    fieldId: event.fieldId || null,
    occurredAt: event.occurredAt || event.recordedAt || null,
    truthLabel: event.truthLabel || "unknown",
    dataQuality: event.dataQuality || "unknown",
  }));
}

export function evidenceReviewSignature(scope = {}, events = []) {
  const ids = events.map((event) => event.id).filter(Boolean).sort();
  return [
    scope.moduleScope || "",
    scope.farmScope || "",
    scope.fieldScope || "",
    scope.blockScope || "",
    scope.dateWindow?.start || "",
    scope.dateWindow?.end || "",
    ids.join(","),
  ].join("|");
}

export function createEvidencePacket(input) {
  const scope = {
    moduleScope: input.moduleScope || "",
    farmScope: input.farmScope || "",
    fieldScope: input.fieldScope || null,
    blockScope: input.blockScope || null,
    dateWindow: input.dateWindow || null,
  };
  const events = input.preFiltered ? input.events || [] : filterEvidenceEvents(input.events || [], scope);
  const artifacts = input.artifacts || [];
  const missingInputs = input.missingInputs || [];
  const reviewSignature = evidenceReviewSignature(scope, events);
  const reviewedEventIds = input.reviewSnapshot?.includedEventIds || input.reviewedEventIds || [];
  const reviewedIdsMatch = JSON.stringify([...reviewedEventIds].sort()) === JSON.stringify(events.map((event) => event.id).filter(Boolean).sort());
  const reviewedSignature = input.reviewSnapshot?.reviewSignature || input.reviewSignature || "";
  const reviewMatches = Boolean(input.reviewConfirmed && reviewedSignature && reviewedSignature === reviewSignature && reviewedIdsMatch);
  const requiredMissing = [];
  if (!input.moduleScope) requiredMissing.push("module scope");
  if (!input.farmScope) requiredMissing.push("farm scope");
  if (!input.dateWindow?.start || !input.dateWindow?.end) requiredMissing.push("date window");
  if (!events.length) requiredMissing.push("filtered ledger evidence");
  if (!reviewMatches) requiredMissing.push("matching reviewed event scope");
  const allMissing = [...requiredMissing, ...missingInputs];
  return {
    id: input.id || `packet-${Date.now()}`,
    title: input.title || "Draft evidence packet",
    status: allMissing.length ? "draft_missing_evidence" : "ready_operational_record",
    moduleScope: input.moduleScope || "unspecified",
    farmScope: input.farmScope || "local-farm",
    fieldScope: input.fieldScope || null,
    blockScope: input.blockScope || null,
    dateWindow: input.dateWindow || null,
    reviewConfirmed: reviewMatches,
    reviewSignature,
    reviewedAt: reviewMatches ? input.reviewSnapshot?.reviewedAt || input.reviewedAt || null : null,
    reviewRows: reviewRowsForEvents(events),
    includedEventIds: events.map((event) => event.id),
    includedEvidenceArtifactIds: artifacts.map((artifact) => artifact.id),
    assumptions: input.assumptions || [],
    missingInputs: allMissing,
    limitations: input.limitations || [],
    generatedAt: new Date().toISOString(),
    truthLabelSummary: [...new Set(events.map((event) => event.truthLabel).filter(Boolean))],
    disclaimer: TERRIS_PROOF_DISCLAIMER,
    representativeDemo: Boolean(input.representativeDemo),
    syncStatus: input.syncStatus || (input.offline ? "queued" : "synced"),
  };
}

export function evidencePacketEvent(packet) {
  return createTerrisFieldEvent({
    eventType: "evidence_packet_generated",
    module: "proof",
    farmId: packet.farmScope,
    fieldId: packet.fieldScope,
    blockId: packet.blockScope,
    sourceRecordId: packet.id,
    sourceMode: packet.representativeDemo ? "demo" : "system",
    truthLabel: "calculated",
    dataQuality: packet.status === "draft_missing_evidence" ? "blocked" : "medium",
    payload: { ...packet, representativeDemo: Boolean(packet.representativeDemo) },
    limitations: packet.limitations,
    queuedForSync: packet.syncStatus === "queued",
  });
}
