const prohibitedPatterns = [
  { pattern: /guarantee(?:d)?\s+(yield|savings|water savings)/i, reason: "removed guaranteed outcome language", replacement: "available data suggests" },
  { pattern: /exact soil moisture/i, reason: "removed unsupported exact soil moisture claim", replacement: "estimated soil moisture" },
  { pattern: /satellite (?:shows|detected|confirms|indicates)/i, reason: "removed unsupported satellite claim", replacement: "Satellite evidence is not available for this recommendation" },
  { pattern: /\bET\s+(?:of|is|=|was)\s+[\d.]+\s*mm/i, reason: "removed unsupported exact ET value claim", replacement: "estimated evapotranspiration (ET source not connected)" },
  { pattern: /apply\s+exactly\s+[\d.]+\s*(?:mm|liters?|gallons?|m³)/i, reason: "removed exact application volume claim", replacement: "Add flow rate to calculate a target volume" },
  { pattern: /irrigate\s+for\s+exactly\s+[\d.]+\s*(?:hours?|minutes?)/i, reason: "removed exact duration claim", replacement: "Add flow rate to calculate a duration" },
  { pattern: /water savings?\s+of\s+[\d]+%/i, reason: "removed unverified water-savings percentage claim", replacement: "potential water savings (not yet verified)" },
  { pattern: /verified\s+water\s+savings/i, reason: "removed unverified savings claim", replacement: "unverified potential savings" },
  { pattern: /stress\s+index\s+(?:of|is)\s+[\d.]+/i, reason: "removed unsupported stress-index value", replacement: "estimated stress level" },
];

const ESCALATION_SAFE = new Set(["irrigate"]);
const NON_ESCALATABLE = new Set(["wait", "monitor", "check field first", "update missing data"]);

function scrubText(text, triggered) {
  let safe = String(text || "");
  for (const item of prohibitedPatterns) {
    if (item.pattern.test(safe)) {
      triggered.push(item.reason);
      safe = safe.replace(item.pattern, item.replacement);
    }
  }
  return safe;
}

function confidenceLabel(score) {
  if (score >= 0.75) return "high";
  if (score >= 0.5) return "moderate";
  return "low";
}

export function containsUnsupportedClaim(text) {
  return prohibitedPatterns.some((item) => item.pattern.test(String(text || "")));
}

export const safetyGuardrails = {
  enforce(decision, context = {}) {
    const triggered = [...(decision.guardrailsTriggered || [])];
    const weather = context.weather || {};
    const deterministic = context.deterministicSignals || {};
    const patched = { ...decision };

    for (const key of ["reasons", "uncertainties", "fieldChecks", "risks", "safetyNotes"]) {
      if (Array.isArray(patched[key])) patched[key] = patched[key].map((text) => scrubText(text, triggered));
    }
    if (Array.isArray(patched.verificationPlan?.checks)) {
      patched.verificationPlan = { ...patched.verificationPlan, checks: patched.verificationPlan.checks.map((text) => scrubText(text, triggered)) };
    } else if (Array.isArray(patched.verificationPlan)) {
      patched.verificationPlan = patched.verificationPlan.map((text) => scrubText(text, triggered));
    }
    patched.nextBestAction = scrubText(patched.nextBestAction, triggered);

    // Specific rule checks run first so their named guardrail keys are always recorded.
    // The generic authority block is a final catch-all for any remaining irrigate escalation.
    if ((deterministic.rulesTriggered || []).includes("frost_risk") && patched.action === "irrigate") {
      patched.action = "check field first";
      patched.fieldChecks = [...(patched.fieldChecks || []), "Confirm frost-specific local protocol before applying water"];
      triggered.push("frost_risk_blocks_generic_irrigation");
    }
    if ((deterministic.rulesTriggered || []).includes("wet_observation") && patched.action === "irrigate") {
      patched.action = "check field first";
      patched.urgency = "medium";
      triggered.push("deterministic_wet_observation_overrode_irrigate");
    }
    if ((deterministic.rulesTriggered || []).includes("rain_likely") && patched.action === "irrigate") {
      patched.action = "wait";
      triggered.push("rain_forecast_blocks_irrigate");
    }
    if ((deterministic.rulesTriggered || []).includes("recent_irrigation") && patched.action === "irrigate" && (deterministic.needScore || 0) < 0.82) {
      patched.action = "check field first";
      triggered.push("recent_irrigation_requires_field_check");
    }

    const deterministicAction = deterministic.action || (deterministic.needScore >= 0.72 ? "irrigate" : deterministic.needScore >= 0.45 ? "check field first" : "monitor");
    if (patched.action === "irrigate" && !ESCALATION_SAFE.has(deterministicAction)) {
      patched.action = deterministicAction || "check field first";
      patched.urgency = deterministic.urgency || "medium";
      triggered.push("deterministic_authority_blocked_irrigate");
    }

    const warnings = [];
    if ((patched.missingData || []).length) warnings.push("Data is incomplete.");
    if (weather.stale) warnings.push("Weather data is stale. Refresh before acting.");
    if (patched.confidenceScore < 0.5) warnings.push("Low confidence: check field before action.");
    if (weather.etLabel === "not provided by OpenWeather") warnings.push("ET source is not connected yet.");
    if (!patched.evidenceQuality?.evidenceChecked?.includes("satellite evidence") && JSON.stringify(patched).toLowerCase().includes("satellite")) {
      warnings.push("Satellite evidence is not available for this recommendation.");
    }
    if (!patched.evidenceQuality?.evidenceChecked?.includes("ET source") && JSON.stringify(patched).toLowerCase().includes(" et ")) {
      warnings.push("ET source is not connected yet.");
    }

    const fieldChecks = new Set([...(patched.fieldChecks || [])]);
    if (patched.confidenceScore < 0.55) fieldChecks.add("Check field conditions before irrigating.");
    if (weather.stale) fieldChecks.add("Weather is stale — confirm local conditions before irrigating.");
    patched.fieldChecks = [...fieldChecks];

    patched.guardrailWarnings = [...new Set(warnings)];
    patched.guardrailsTriggered = [...new Set(triggered)];
    patched.confidenceLabel = patched.confidenceLabel || confidenceLabel(patched.confidenceScore || 0);
    patched.disclaimer = "Recommendation support only. Validate in-field conditions before acting.";
    return patched;
  },
};
