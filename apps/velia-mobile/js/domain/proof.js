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
  return {
    id: input.id || `packet-${Date.now()}`,
    title: input.title,
    moduleScope: input.moduleScope || "cross_module",
    farmScope: input.farmScope || "local-farm",
    fieldScope: input.fieldScope || null,
    blockScope: input.blockScope || null,
    dateWindow: input.dateWindow,
    includedEventIds: events.map((event) => event.id),
    includedEvidenceArtifactIds: artifacts.map((artifact) => artifact.id),
    assumptions: input.assumptions || [],
    missingInputs: input.missingInputs || [],
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
    payload: packet,
    limitations: packet.limitations,
  });
}
