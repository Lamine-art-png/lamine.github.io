import fs from "fs";
import path from "path";
import { config } from "../config.js";

const filePath = path.resolve(config.memoryFile);

function loadJson() {
  try { return JSON.parse(fs.readFileSync(filePath, "utf8")); } catch { return { farms: {}, fields: {} }; }
}
function saveJson(data) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
}

export const memoryStore = {
  getFieldMemory(fieldId) {
    const db = loadJson();
    return db.fields[fieldId] || { fieldId, recommendationHistory: [], irrigationLogs: [], observations: [], voiceNotes: [], verificationOutcomes: [], recurringMissingData: [] };
  },
  updateFieldMemory(fieldId, event) {
    const db = loadJson();
    const entry = db.fields[fieldId] || this.getFieldMemory(fieldId);
    entry.events = entry.events || [];
    entry.events.unshift({ ...event, ts: new Date().toISOString() });
    if (event.type === "decision") entry.recommendationHistory.unshift(event.payload);
    if (event.type === "irrigation_log") entry.irrigationLogs.unshift(event.payload);
    if (event.type === "observation") entry.observations.unshift(event.payload);
    if (event.type === "voice") entry.voiceNotes.unshift(event.payload);
    if (event.type === "verification") entry.verificationOutcomes.unshift(event.payload);
    db.fields[fieldId] = entry;
    saveJson(db);
    return entry;
  },
  summarizeFieldMemory(fieldId) {
    const m = this.getFieldMemory(fieldId);
    return { fieldId, recommendationHistory: m.recommendationHistory.slice(0, 3), recentLogs: m.irrigationLogs.slice(0, 3), recentObservations: m.observations.slice(0, 3) };
  },
  retrieveRelevantMemory(fieldId, query) {
    const m = this.getFieldMemory(fieldId);
    const q = String(query || "").toLowerCase();
    return (m.events || []).filter((e) => JSON.stringify(e).toLowerCase().includes(q)).slice(0, 5);
  },
};
