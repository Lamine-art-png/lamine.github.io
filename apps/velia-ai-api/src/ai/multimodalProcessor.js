export const multimodalProcessor = {
  classifyText(note = "") {
    const text = note.toLowerCase();
    if (text.includes("dry")) return { signal: "dry_stress" };
    if (text.includes("wet")) return { signal: "too_wet" };
    return { signal: "neutral" };
  },
  classifyVoiceTranscript(transcript = "") {
    const text = transcript.toLowerCase();
    if (text.includes("log irrigation")) return { intent: "log irrigation" };
    if (text.includes("looks dry")) return { intent: "update field condition" };
    if (text.includes("why")) return { intent: "explain recommendation" };
    return { intent: "daily irrigation decision" };
  },
  imagePlaceholder() {
    return { status: "not_implemented" };
  },
};
