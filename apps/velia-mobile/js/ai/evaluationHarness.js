export const evaluationScenarios = [
  "sparse-data manual farm",
  "high heat",
  "rain expected soon",
  "unknown soil type",
  "stale weather",
  "dry field observation",
  "too-wet observation",
  "sensor-connected field",
  "controller-connected field",
  "missing crop",
  "recent irrigation",
  "missed verification",
  "farmer override",
  "conflicting signals",
  "low-confidence case",
  "multilingual explanation request",
  "provider timeout",
  "invalid LLM JSON",
  "weather API unavailable",
  "RAG retrieval unavailable",
  "heat plus rain conflict",
  "frost risk",
  "missing field coordinates",
  "missing last irrigation",
  "manual voice note",
  "repeated dryness",
  "repeated stale-weather fallback",
  "sensor says too wet",
  "controller offline",
  "offline local fallback",
];

export function evaluateDecisionScenario(name, decision) {
  const checks = {
    reasonableAction: Boolean(decision.action),
    confidenceExposed: typeof decision.confidenceScore === "number",
    missingDataExposed: Array.isArray(decision.missingData),
    explanationClear: Array.isArray(decision.reasons) && decision.reasons.length > 0,
    guardrailsPresent: Boolean(decision.disclaimer),
  };
  return { scenario: name, checks, passed: Object.values(checks).every(Boolean) };
}

export function runEvaluationHarness(decisionFactory) {
  return evaluationScenarios.map((scenario) => evaluateDecisionScenario(scenario, decisionFactory(scenario)));
}
