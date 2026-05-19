export const scenarios = [
  "sparse data farm",
  "manual irrigation farm",
  "high heat and dry field",
  "rain expected soon",
  "unknown soil type",
  "stale weather",
  "connected controller scenario",
  "user overrides recommendation",
  "voice log irrigation",
  "ask why confidence is low",
  "ask in another language",
];

export function evaluateDecision(decision) {
  const checks = {
    actionReasonable: Boolean(decision.action),
    confidenceValid: typeof decision.confidenceScore === "number",
    missingDataVisible: Array.isArray(decision.missingData),
    explanationClear: Array.isArray(decision.reasons) && decision.reasons.length > 0,
    guardrailsApplied: Boolean(decision.disclaimer),
  };
  return { checks, passed: Object.values(checks).every(Boolean) };
}
