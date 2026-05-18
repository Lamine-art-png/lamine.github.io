import { detectIntent } from "../services/voiceAgent.js";

export const multimodalProcessor = {
  classifyTextNote(note) {
    const text = String(note || "").toLowerCase();
    if (text.includes("dry") || text.includes("stressed")) return { signal: "dry_stress", severity: "medium" };
    if (text.includes("wet")) return { signal: "excess_moisture", severity: "medium" };
    return { signal: "neutral", severity: "low" };
  },
  classifyVoiceTranscript(transcript) {
    return { intent: detectIntent(transcript), transcript };
  },
  analyzeImagePlaceholder() {
    return { status: "not_implemented", planned: ["crop_stress", "wet_dry_signal", "disease_suspicion", "irrigation_issue_evidence"] };
  },
};
