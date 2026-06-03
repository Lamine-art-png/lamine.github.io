const fieldMemory = new Map();
const MAX_MEMORY_ITEMS = 50;

function decisionKey(decision = {}) {
  return [decision.fieldId, decision.action, decision.urgency, decision.timing, decision.confidenceLabel ?? decision.confidenceScore].join("|");
}

function addCappedUnique(list, item, keyFn = (value) => JSON.stringify(value), cap = MAX_MEMORY_ITEMS) {
  const key = keyFn(item);
  const next = [item, ...list.filter((existing) => keyFn(existing) !== key)];
  return next.slice(0, cap);
}

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
    memory.events = addCappedUnique(memory.events, { ...event, ts: new Date().toISOString() }, (value) => `${value.type}:${JSON.stringify(value.payload)}`, 100);
    if (event.type === "decision") memory.recommendationHistory = addCappedUnique(memory.recommendationHistory, event.payload, decisionKey);
    if (event.type === "irrigation_log") memory.irrigationLogs = addCappedUnique(memory.irrigationLogs, event.payload, (value) => value.id || JSON.stringify(value));
    if (event.type === "observation") memory.observations = addCappedUnique(memory.observations, event.payload, (value) => value.id || JSON.stringify(value));
    if (event.type === "voice_note") memory.voiceNotes = addCappedUnique(memory.voiceNotes, event.payload, (value) => value.id || JSON.stringify(value));
    if (event.type === "verification") memory.verificationOutcomes = addCappedUnique(memory.verificationOutcomes, event.payload, (value) => value.id || JSON.stringify(value));
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
