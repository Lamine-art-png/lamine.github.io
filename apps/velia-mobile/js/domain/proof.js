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

export function createEvidencePacket(input) {
  const events = input.events || [];
  const artifacts = input.artifacts || [];
  const missingInputs = input.missingInputs || [];
  const requiredMissing = [];
  if (!input.moduleScope) requiredMissing.push("module scope");
  if (!input.farmScope) requiredMissing.push("farm scope");
  if (!input.dateWindow?.start || !input.dateWindow?.end) requiredMissing.push("date window");
  if (!events.length) requiredMissing.push("included event review");
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
    includedEventIds: events.map((event) => event.id),
    includedEvidenceArtifactIds: artifacts.map((artifact) => artifact.id),
    assumptions: input.assumptions || [],
    missingInputs: allMissing,
    limitations: input.limitations || [],
    generatedAt: new Date().toISOString(),
    truthLabelSummary: [...new Set(events.map((event) => event.truthLabel).filter(Boolean))],
    disclaimer: TERRIS_PROOF_DISCLAIMER,
  };
}

export function evidencePacketEvent(packet) {
  return createTerrisFieldEvent({
    eventType: "evidence_packet_generated",
    module: "proof",
    fieldId: packet.fieldScope,
    sourceRecordId: packet.id,
    sourceMode: "system",
    truthLabel: "calculated",
    dataQuality: packet.status === "draft_missing_evidence" ? "blocked" : "medium",
    payload: packet,
    limitations: packet.limitations,
  });
}
