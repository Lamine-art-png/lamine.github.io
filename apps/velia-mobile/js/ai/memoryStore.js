const fieldMemory = new Map();

function initFieldMemory(fieldId) {
  if (!fieldMemory.has(fieldId)) {
    fieldMemory.set(fieldId, {
      fieldId,
      profile: null,
      recommendationHistory: [],
      irrigationLogs: [],
      observations: [],
      voiceNotes: [],
      userOverrides: [],
      recurringIssues: [],
      confidenceChanges: [],
      missingDataPatterns: [],
      verificationOutcomes: [],
      events: [],
    });
  }
  return fieldMemory.get(fieldId);
}

export const memoryStore = {
  getFieldMemory(fieldId) {
    return initFieldMemory(fieldId);
  },
  updateFieldMemory(fieldId, event) {
    const memory = initFieldMemory(fieldId);
    memory.events.unshift({ ...event, ts: new Date().toISOString() });
    if (event.type === "decision") memory.recommendationHistory.unshift(event.payload);
    if (event.type === "irrigation_log") memory.irrigationLogs.unshift(event.payload);
    if (event.type === "observation") memory.observations.unshift(event.payload);
    if (event.type === "voice_note") memory.voiceNotes.unshift(event.payload);
    if (event.type === "verification") memory.verificationOutcomes.unshift(event.payload);
    return memory;
  },
  summarizeFieldMemory(fieldId) {
    const m = initFieldMemory(fieldId);
    return {
      fieldId,
      recentDecisions: m.recommendationHistory.slice(0, 3),
      recurringIssues: m.recurringIssues.slice(0, 3),
      recentConfidence: m.confidenceChanges.slice(0, 3),
      missingDataPatterns: m.missingDataPatterns.slice(0, 3),
    };
  },
  retrieveRelevantMemory(fieldId, query) {
    const m = initFieldMemory(fieldId);
    const q = String(query || "").toLowerCase();
    return m.events.filter((e) => JSON.stringify(e).toLowerCase().includes(q)).slice(0, 5);
  },
};
