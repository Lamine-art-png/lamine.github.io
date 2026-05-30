const prohibitedPatterns = [
  { pattern: /guarantee(?:d)?\s+(yield|savings|water savings)/i, reason: "removed guaranteed outcome language" },
  { pattern: /exact soil moisture/i, reason: "removed unsupported exact soil moisture claim" },
  { pattern: /satellite (?:shows|detected)/i, reason: "removed unsupported satellite claim" },
];

function scrubText(text, triggered) {
  let safe = String(text || "");
  for (const item of prohibitedPatterns) {
    if (item.pattern.test(safe)) {
      triggered.push(item.reason);
      safe = safe.replace(item.pattern, "available data suggests");
    }
  }
  return safe;
}

function confidenceLabel(score) {
  if (score >= 0.75) return "high";
  if (score >= 0.5) return "moderate";
  return "low";
}

export const safetyGuardrails = {
  enforce(decision, context = {}) {
    const triggered = [...(decision.guardrailsTriggered || [])];
    const weather = context.weather || {};
    const deterministic = context.deterministicSignals || {};
    const patched = { ...decision };

    for (const key of ["reasons", "uncertainties", "fieldChecks", "risks", "safetyNotes", "verificationPlan"]) {
      if (Array.isArray(patched[key])) patched[key] = patched[key].map((text) => scrubText(text, triggered));
    }
    patched.nextBestAction = scrubText(patched.nextBestAction, triggered);

    if ((deterministic.rulesTriggered || []).includes("wet_observation") && patched.action === "irrigate") {
      patched.action = "check field first";
      patched.urgency = "medium";
      triggered.push("deterministic_wet_observation_overrode_irrigate");
    }
    if ((deterministic.rulesTriggered || []).includes("recent_irrigation") && patched.action === "irrigate" && deterministic.needScore < 0.82) {
      patched.action = "check field first";
      triggered.push("recent_irrigation_requires_field_check");
    }
    if ((deterministic.rulesTriggered || []).includes("frost_risk") && patched.action === "irrigate") {
      patched.action = "check field first";
      patched.fieldChecks = [...(patched.fieldChecks || []), "Confirm frost-specific local protocol before applying water"];
      triggered.push("frost_risk_blocks_generic_irrigation");
    }

    const warnings = [];
    if ((patched.missingData || []).length) warnings.push("Data is incomplete.");
    if (weather.stale) warnings.push("Weather data is stale.");
    if (patched.confidenceScore < 0.5) warnings.push("Low confidence: check field before action.");
    if (weather.etLabel === "not provided by OpenWeather") warnings.push("No exact ET source was available from the weather provider.");

    const fieldChecks = new Set([...(patched.fieldChecks || [])]);
    if (patched.confidenceScore < 0.55) fieldChecks.add("Check field conditions before irrigating");
    patched.fieldChecks = [...fieldChecks];

    patched.guardrailWarnings = [...new Set(warnings)];
    patched.guardrailsTriggered = [...new Set(triggered)];
    patched.confidenceLabel = patched.confidenceLabel || confidenceLabel(patched.confidenceScore || 0);
    patched.disclaimer = "Recommendation support only. Validate in-field conditions before acting.";
    return patched;
  },
};
