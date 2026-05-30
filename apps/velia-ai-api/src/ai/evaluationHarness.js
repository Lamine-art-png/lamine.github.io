export const scenarios = [
  { id: "sparse-data-manual-farm", category: "sparse-data manual farm" },
  { id: "high-heat", category: "high heat" },
  { id: "rain-expected-soon", category: "rain expected soon" },
  { id: "unknown-soil-type", category: "unknown soil type" },
  { id: "stale-weather", category: "stale weather" },
  { id: "dry-field-observation", category: "dry field observation" },
  { id: "too-wet-observation", category: "too-wet observation" },
  { id: "sensor-connected-field", category: "sensor-connected field" },
  { id: "controller-connected-field", category: "controller-connected field" },
  { id: "missing-crop", category: "missing crop" },
  { id: "recent-irrigation", category: "recent irrigation" },
  { id: "missed-verification", category: "missed verification" },
  { id: "farmer-override", category: "farmer override" },
  { id: "conflicting-signals", category: "conflicting signals" },
  { id: "low-confidence-case", category: "low-confidence case" },
  { id: "multilingual-explanation-request", category: "multilingual explanation request" },
  { id: "provider-timeout", category: "provider timeout" },
  { id: "invalid-llm-json", category: "invalid LLM JSON" },
  { id: "weather-api-unavailable", category: "weather API unavailable" },
  { id: "rag-retrieval-unavailable", category: "RAG retrieval unavailable" },
  { id: "heat-plus-rain-conflict", category: "high heat with rain forecast" },
  { id: "frost-risk", category: "frost risk" },
  { id: "no-coordinates", category: "missing field coordinates" },
  { id: "missing-last-irrigation", category: "missing last irrigation" },
  { id: "manual-voice-note", category: "voice note only" },
  { id: "repeated-dryness", category: "recurring repeated dryness" },
  { id: "repeated-stale-weather", category: "recurring stale-weather fallback" },
  { id: "sensor-high-moisture", category: "sensor says too wet" },
  { id: "controller-offline", category: "controller offline" },
  { id: "offline-local-fallback", category: "offline fallback" },
];

function includesForbiddenFabrication(decision) {
  const text = JSON.stringify(decision || {}).toLowerCase();
  return /exact soil moisture|guaranteed yield|guaranteed water savings|satellite shows/.test(text);
}

export function evaluateDecision(decision) {
  const provenance = decision.provenance || {};
  const checks = {
    reasonableAction: Boolean(decision.action),
    confidenceBehavior: typeof decision.confidenceScore === "number" && decision.confidenceScore >= 0 && decision.confidenceScore <= 1,
    noFabricatedData: !includesForbiddenFabrication(decision),
    guardrails: Boolean(decision.disclaimer) && Array.isArray(decision.guardrailWarnings),
    clearMissingDataHandling: Array.isArray(decision.missingData) && Array.isArray(decision.uncertainties),
    fallbackBehavior: Boolean(provenance.fallbackStatus) || provenance.providerMode === "live",
    provenancePresence: Boolean(provenance.decisionTimestamp && provenance.dataSourcesChecked && provenance.deterministicRulesTriggered),
    ragSourcesTracked: Array.isArray(decision.knowledgeSources || provenance.ragSourcesUsed),
    verificationPlanPresent: Boolean(decision.verificationPlan),
  };
  return { checks, passed: Object.values(checks).every(Boolean) };
}

export function runEvaluationHarness(decisionFactory) {
  return scenarios.map((scenario) => {
    const decision = decisionFactory(scenario);
    return { scenario, ...evaluateDecision(decision) };
  });
}
