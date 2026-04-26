export function detectIntent(text = "") {
  const normalized = text.toLowerCase();
  if (/should i irrigate today/.test(normalized)) return "ASK_RECOMMENDATION";
  if (/why is confidence/.test(normalized)) return "EXPLAIN_RECOMMENDATION";
  if (/what changed since yesterday/.test(normalized)) return "WHAT_CHANGED";
  if (/log irrigation|irrigation/.test(normalized)) return "LOG_IRRIGATION";
  if (/looks dry|looks too wet|looks normal|leaves look stressed|i am not sure/.test(normalized)) return "UPDATE_CONDITION";
  if (/field note|add note/.test(normalized)) return "ADD_FIELD_NOTE";
  return "UNKNOWN";
}
