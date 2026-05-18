export const safetyGuardrails = {
  enforce(decision, weather = {}) {
    const warnings = [];
    if ((decision.missingData || []).length) warnings.push("Data is incomplete.");
    if (weather.stale) warnings.push("Weather data is stale.");
    if (decision.confidenceScore < 0.5) warnings.push("Low confidence: check field before action.");

    return {
      ...decision,
      guardrailWarnings: warnings,
      disclaimer: "Recommendation support only. Validate in-field conditions.",
    };
  },
};
