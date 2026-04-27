export const evaluationScenarios = [
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
