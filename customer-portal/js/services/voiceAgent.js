import { syncService } from "./syncService.js";

const mockTranscripts = [
  "Should I irrigate Field 2 today?",
  "Log irrigation on Field 1 for 45 minutes.",
  "Add a note that soil is dry near the south edge.",
];

const intentRules = [
  { match: /should i irrigate|recommend/i, intent: "ASK_RECOMMENDATION" },
  { match: /explain/i, intent: "EXPLAIN_RECOMMENDATION" },
  { match: /log irrigation|irrigation on/i, intent: "LOG_IRRIGATION" },
  { match: /add a note|note/i, intent: "ADD_FIELD_NOTE" },
  { match: /alerts/i, intent: "READ_ALERTS" },
  { match: /reminder/i, intent: "CREATE_REMINDER" },
  { match: /language/i, intent: "SWITCH_LANGUAGE" },
  { match: /open field/i, intent: "OPEN_FIELD" },
];

export const voiceAgent = {
  startListening(language = "en", fieldId = "") {
    return { id: `vs-${Date.now()}`, language, fieldId, startedAt: new Date().toISOString(), status: "listening" };
  },
  stopListening(session) {
    return { ...session, status: "processing", endedAt: new Date().toISOString() };
  },
  transcribe(session) {
    const text = mockTranscripts[Math.floor(Math.random() * mockTranscripts.length)];
    return { id: `vt-${Date.now()}`, sessionId: session.id, language: session.language, text, confidence: 0.79, createdAt: new Date().toISOString(), source: "mock_stt" };
  },
  detectIntent(transcript) {
    const hit = intentRules.find((rule) => rule.match.test(transcript.text));
    return {
      id: `vc-${Date.now()}`,
      sessionId: transcript.sessionId,
      transcriptId: transcript.id,
      intent: hit?.intent || "UNKNOWN",
      entities: {},
      confidence: hit ? 0.73 : 0.41,
    };
  },
  executeVoiceAction(command, context = {}) {
    if (command.intent === "ADD_FIELD_NOTE") {
      return { id: `va-${Date.now()}`, type: "save_note", payload: { text: context.transcript?.text, fieldId: context.fieldId } };
    }
    if (command.intent === "LOG_IRRIGATION") {
      return { id: `va-${Date.now()}`, type: "log_irrigation", payload: { fieldId: context.fieldId, source: "voice" }, requiresLiveData: false };
    }
    if (command.intent === "OPEN_FIELD") {
      return { id: `va-${Date.now()}`, type: "navigate", payload: { route: "fields" } };
    }
    return { id: `va-${Date.now()}`, type: "noop", payload: {}, requiresLiveData: true };
  },
  speakResponse(response) {
    return { ...response, spoken: true };
  },
  saveOfflineVoiceAction(action) {
    syncService.enqueue({ ...action, kind: "voice_action" });
  },
  async syncQueuedVoiceActions() {
    return syncService.syncQueuedActions();
  },
  composeResponse({ recommendation, command, offline }) {
    if (offline && command.type === "noop") {
      return "I saved your request. I will update it when connection returns.";
    }
    if (recommendation) {
      return `Based on current weather and your last irrigation, ${recommendation.fieldName} is priority. ${recommendation.action} Confidence is ${recommendation.confidence}.`;
    }
    return "I captured that. I will keep your field record updated.";
  },
};
