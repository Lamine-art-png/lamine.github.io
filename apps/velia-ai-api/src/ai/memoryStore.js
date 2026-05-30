import fs from "fs";
import path from "path";
import { config } from "../config.js";
import { MemoryProvider } from "../providers/MemoryProvider.js";

const filePath = path.resolve(config.memoryFile);

function emptyFieldMemory(fieldId) {
  return {
    fieldId,
    recommendationHistory: [],
    recommendations: [],
    irrigationLogs: [],
    observations: [],
    fieldObservations: [],
    userOverrides: [],
    voiceNotes: [],
    missingDataPatterns: [],
    verificationOutcomes: [],
    providerProvenance: [],
    recurringPatterns: [],
    events: [],
  };
}

function loadJson() {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return { farms: {}, fields: {} };
  }
}

function saveJson(data) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
}

function countRecent(items, predicate, limit = 8) {
  return (items || []).slice(0, limit).filter(predicate).length;
}

export function detectRecurringPatterns(memory) {
  const patterns = [];
  const dryCount = countRecent(memory.observations, (item) => /dry|stress|wilting/i.test(item.condition || item.note || ""));
  if (dryCount >= 2) patterns.push({ type: "repeated_dryness", count: dryCount, severity: dryCount >= 3 ? "high" : "medium" });

  const missedCount = countRecent(memory.verificationOutcomes, (item) => /not_followed|no_confirmation|missed/i.test(item.status || item.details || ""));
  if (missedCount >= 2) patterns.push({ type: "repeated_missed_irrigation_or_verification", count: missedCount, severity: "medium" });

  const lowConfidenceCount = countRecent(memory.recommendationHistory, (item) => Number(item.confidenceScore ?? item.rec?.confidenceScore ?? 1) < 0.5);
  if (lowConfidenceCount >= 2) patterns.push({ type: "repeated_low_confidence_decisions", count: lowConfidenceCount, severity: "medium" });

  const staleCount = countRecent(memory.providerProvenance, (item) => item.weatherStale || /stale/i.test(item.fallbackStatus || ""));
  if (staleCount >= 2) patterns.push({ type: "repeated_stale_weather_fallback", count: staleCount, severity: "medium" });

  const overrideCount = countRecent(memory.userOverrides, () => true);
  if (overrideCount >= 2) patterns.push({ type: "repeated_override_behavior", count: overrideCount, severity: "medium" });

  return patterns.map((pattern) => ({ ...pattern, detectedAt: new Date().toISOString() }));
}

class JsonMemoryProvider extends MemoryProvider {
  constructor() {
    super("json");
  }

  getFieldMemory(fieldId) {
    const db = loadJson();
    return { ...emptyFieldMemory(fieldId), ...(db.fields[fieldId] || {}) };
  }

  updateFieldMemory(fieldId, event) {
    const db = loadJson();
    const entry = { ...emptyFieldMemory(fieldId), ...(db.fields[fieldId] || {}) };
    const ts = new Date().toISOString();
    const eventWithTs = { ...event, ts };
    entry.events = entry.events || [];
    entry.events.unshift(eventWithTs);
    entry.events = entry.events.slice(0, 250);

    if (event.type === "decision") {
      entry.recommendationHistory.unshift(event.payload);
      entry.recommendations.unshift(event.payload);
      if (event.payload?.provenance) entry.providerProvenance.unshift(event.payload.provenance);
      for (const missing of event.payload?.missingData || []) entry.missingDataPatterns.unshift({ item: missing, ts });
    }
    if (event.type === "recommendation") entry.recommendations.unshift(event.payload);
    if (event.type === "irrigation_log") entry.irrigationLogs.unshift(event.payload);
    if (event.type === "observation") {
      entry.observations.unshift(event.payload);
      entry.fieldObservations.unshift(event.payload);
    }
    if (event.type === "override") entry.userOverrides.unshift(event.payload);
    if (event.type === "voice") entry.voiceNotes.unshift(event.payload);
    if (event.type === "verification") entry.verificationOutcomes.unshift(event.payload);
    if (event.type === "provider_provenance") entry.providerProvenance.unshift(event.payload);

    for (const key of ["recommendationHistory", "recommendations", "irrigationLogs", "observations", "fieldObservations", "userOverrides", "voiceNotes", "missingDataPatterns", "verificationOutcomes", "providerProvenance"]) {
      entry[key] = (entry[key] || []).slice(0, 80);
    }

    entry.recurringPatterns = detectRecurringPatterns(entry);
    db.fields[fieldId] = entry;
    saveJson(db);
    return entry;
  }

  summarizeFieldMemory(fieldId) {
    const m = this.getFieldMemory(fieldId);
    return {
      fieldId,
      recommendationHistory: m.recommendationHistory.slice(0, 3),
      recentLogs: m.irrigationLogs.slice(0, 3),
      recentObservations: m.observations.slice(0, 3),
      verificationOutcomes: m.verificationOutcomes.slice(0, 3),
      recurringPatterns: m.recurringPatterns.slice(0, 5),
    };
  }

  retrieveRelevantMemory(fieldId, query) {
    const m = this.getFieldMemory(fieldId);
    const q = String(query || "").toLowerCase();
    return (m.events || []).filter((e) => JSON.stringify(e).toLowerCase().includes(q)).slice(0, 5);
  }
}

export const memoryProvider = new JsonMemoryProvider();

export const memoryStore = {
  getFieldMemory(fieldId) {
    return memoryProvider.getFieldMemory(fieldId);
  },
  updateFieldMemory(fieldId, event) {
    return memoryProvider.updateFieldMemory(fieldId, event);
  },
  summarizeFieldMemory(fieldId) {
    return memoryProvider.summarizeFieldMemory(fieldId);
  },
  retrieveRelevantMemory(fieldId, query) {
    return memoryProvider.retrieveRelevantMemory(fieldId, query);
  },
  detectRecurringPatterns,
};
