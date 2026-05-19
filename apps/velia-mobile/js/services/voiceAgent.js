import { syncService } from "./sync.js";

export function detectIntent(text) {
  const t = text.toLowerCase();
  if (/should i irrigate today/.test(t)) return "ASK_RECOMMENDATION";
  if (/why is confidence/.test(t)) return "EXPLAIN_RECOMMENDATION";
  if (/what changed since yesterday/.test(t)) return "WHAT_CHANGED";
  if (/log irrigation|irrigation/.test(t)) return "LOG_IRRIGATION";
  if (/looks dry|looks too wet|looks normal|leaves look stressed|i am not sure/.test(t)) return "UPDATE_CONDITION";
  if (/field note|add note/.test(t)) return "ADD_FIELD_NOTE";
  return "UNKNOWN";
}

const conditionMap = ["Looks normal", "Looks dry", "Looks too wet", "Leaves look stressed", "I am not sure"];

export function parseVoiceCommand(text, context = {}) {
  const intent = detectIntent(text);
  const numberDuration = text.match(/(\d+)\s*(hour|hours|minute|minutes)/i);
  const durationMin = numberDuration ? Number(numberDuration[1]) * (/hour/i.test(numberDuration[2]) ? 60 : 1) : 60;

  if (intent === "LOG_IRRIGATION") {
    return { intent, action: { type: "log_irrigation", payload: { fieldId: context.fieldId, durationMin, amountMm: Math.round(durationMin * 0.2), source: "voice" } } };
  }

  if (intent === "UPDATE_CONDITION") {
    const condition = conditionMap.find((c) => text.toLowerCase().includes(c.toLowerCase().replace("I am ", "i am "))) || "Looks dry";
    return { intent, action: { type: "update_condition", payload: { fieldId: context.fieldId, condition, source: "voice" } } };
  }

  if (intent === "ADD_FIELD_NOTE") {
    return { intent, action: { type: "add_note", payload: { fieldId: context.fieldId, text, source: "voice" } } };
  }

  return { intent, action: { type: "noop", payload: { text } } };
}

export function applyVoiceAction(command, handlers) {
  if (command.action.type === "log_irrigation") return handlers.onIrrigation(command.action.payload);
  if (command.action.type === "update_condition") return handlers.onCondition(command.action.payload);
  if (command.action.type === "add_note") return handlers.onNote(command.action.payload);
  return handlers.onNoop?.(command.action.payload, command.intent);
}

export const saveOfflineVoiceAction = (action) => syncService.queueAction({ kind: "voice", ...action });
