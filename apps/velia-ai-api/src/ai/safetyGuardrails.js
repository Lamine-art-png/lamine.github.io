import { validateSensor, validateWeather } from "./confidenceEngine.js";

const prohibitedPatterns = [
  { pattern: /guarantee(?:d)?\s+(yield|savings|water savings)/i, reason: "removed guaranteed outcome language", replacement: "available data suggests" },
  { pattern: /exact soil moisture/i, reason: "removed unsupported exact soil moisture claim", replacement: "estimated soil moisture" },
  { pattern: /satellite (?:shows|detected|confirms|indicates)/i, reason: "removed unsupported satellite claim", replacement: "Satellite evidence is not available for this recommendation" },
  { pattern: /\bET\s+(?:of|is|=|was)\s+[\d.]+\s*mm/i, reason: "removed unsupported exact ET value claim", replacement: "estimated evapotranspiration (ET source not connected)" },
  { pattern: /apply\s+exactly\s+[\d.]+\s*(?:mm|liters?|gallons?|m³|inch(?:es)?|acre-f(?:eet|oot)|in\b)/i, reason: "removed exact application volume claim", replacement: "Add flow rate to calculate a target volume" },
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

function makeConditionalPatterns(ctx) {
  const patterns = [];
  if (!validateSensor(ctx?.sensorData, ctx).usable) {
    patterns.push({ pattern: /soil moisture\s+(?:is|of|at|was)\s+[\d.]+\s*%?/i, reason: "removed unsupported soil moisture value (no usable sensor)", replacement: "estimated soil moisture (sensor not connected)" });
  }
  const hasEt = Boolean(ctx?.etProvenance || ctx?.weather?.evapotranspiration);
  if (!hasEt) {
    patterns.push({ pattern: /\bET\s+(?:rate\s+)?(?:is|of|at|was|=)\s+[\d.]+\s*mm/i, reason: "removed unsupported ET value (no ET source)", replacement: "estimated evapotranspiration (ET source not connected)" });
  }
  // Both fields required — one alone is insufficient to validate duration or volume claims
  const hasSystemEvidence = Boolean(ctx?.flowRateLph && ctx?.applicationRateMmPerHour);
  if (!hasSystemEvidence) {
    patterns.push(
      { pattern: /irrigate\s+for\s+[\d.]+\s*(?:hours?|minutes?)/i, reason: "removed duration claim (incomplete system evidence)", replacement: "Add flow rate, application rate, target depth, and field details to calculate a duration." },
      { pattern: /apply\s+[\d.]+\s*(?:mm|liters?|gallons?|m³|inch(?:es)?|acre-f(?:eet|oot)|in\b)/i, reason: "removed volume claim (incomplete system evidence)", replacement: "Add flow rate to calculate a target volume" },
    );
  }
  const hasSatellite = Boolean(ctx?.satelliteEvidence || ctx?.ndvi != null);
  if (!hasSatellite) {
    patterns.push({ pattern: /satellite\s+(?:data|imagery|shows?|indicates?|confirms?|detected?)/i, reason: "removed unsupported satellite claim", replacement: "Satellite evidence is not available for this recommendation" });
  }
  return patterns;
}

function scrubTextWithContext(text, triggered, ctx) {
  let safe = scrubText(text, triggered);
  for (const item of makeConditionalPatterns(ctx)) {
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

export function containsUnsupportedClaimForContext(text, context = {}) {
  if (containsUnsupportedClaim(text)) return true;
  const t = String(text || "");
  if (!validateSensor(context?.sensorData, context).usable && /soil moisture\s+(?:is|of|at|was)\s+[\d.]+\s*%?/i.test(t)) return true;
  const hasEt = Boolean(context?.etProvenance || context?.weather?.evapotranspiration);
  if (!hasEt && /\bET\s+(?:rate\s+)?(?:is|of|at|was|=)\s+[\d.]+\s*mm/i.test(t)) return true;
  // Both fields required for duration/volume claims
  const hasSystemEvidence = Boolean(context?.flowRateLph && context?.applicationRateMmPerHour);
  if (!hasSystemEvidence && /irrigate\s+for\s+[\d.]+\s*(?:hours?|minutes?)/i.test(t)) return true;
  if (!hasSystemEvidence && /apply\s+[\d.]+\s*(?:mm|liters?|gallons?|m³|inch(?:es)?|acre-f(?:eet|oot)|in\b)/i.test(t)) return true;
  const hasSatellite = Boolean(context?.satelliteEvidence || context?.ndvi != null);
  if (!hasSatellite && /satellite\s+(?:data|imagery|shows?|indicates?|confirms?|detected?)/i.test(t)) return true;
  return false;
}

export const safetyGuardrails = {
  enforce(decision, context = {}) {
    const triggered = [...(decision.guardrailsTriggered || [])];
    const weather = context.weather || {};
    const deterministic = context.deterministicSignals || {};
    const fieldContext = context.fieldContext || null;
    const patched = { ...decision };

    // Scrub every user-visible model-generated string field
    for (const key of ["reasons", "uncertainties", "fieldChecks", "risks", "safetyNotes"]) {
      if (Array.isArray(patched[key])) patched[key] = patched[key].map((text) => scrubTextWithContext(text, triggered, fieldContext));
    }
    if (Array.isArray(patched.verificationPlan?.checks)) {
      patched.verificationPlan = { ...patched.verificationPlan, checks: patched.verificationPlan.checks.map((text) => scrubTextWithContext(text, triggered, fieldContext)) };
    } else if (Array.isArray(patched.verificationPlan)) {
      patched.verificationPlan = patched.verificationPlan.map((text) => scrubTextWithContext(text, triggered, fieldContext));
    }
    if (typeof patched.timing === "string") patched.timing = scrubTextWithContext(patched.timing, triggered, fieldContext);
    if (typeof patched.estimatedDurationRange === "string") patched.estimatedDurationRange = scrubTextWithContext(patched.estimatedDurationRange, triggered, fieldContext);
    patched.nextBestAction = scrubTextWithContext(patched.nextBestAction, triggered, fieldContext);

    // Specific rule checks run first so their named guardrail keys are always recorded.
    // The generic authority block is a final catch-all for any remaining irrigate escalation.
    const sensorData = fieldContext?.sensorData || null;
    if ((deterministic.rulesTriggered || []).includes("sensor_high_moisture") && patched.action === "irrigate") {
      if (sensorData && !validateSensor(sensorData, fieldContext).usable) {
        // Stale/unusable high-moisture reading — require field verification rather than trusting unverified value
        patched.action = "check field first";
        triggered.push("sensor_high_moisture_stale_requires_field_check");
      } else {
        patched.action = "wait";
        triggered.push("sensor_high_moisture_blocks_irrigate");
      }
    }
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
    if ((deterministic.rulesTriggered || []).includes("recent_irrigation") && patched.action === "irrigate") {
      const validated = validateSensor(sensorData, fieldContext);
      const sensorConfirmsDry = validated.hardenedForBypass && typeof validated.moisture === "number" && validated.moisture <= 18;
      if (!sensorConfirmsDry) {
        patched.action = "check field first";
        triggered.push("recent_irrigation_requires_field_check");
      }
    }
    // Raw high-moisture from any unusable sensor (stale, no timestamp, no provenance, mismatched) must not
    // silently allow irrigate — downgrade and require field verification.
    if (patched.action === "irrigate" && !triggered.includes("sensor_high_moisture_stale_requires_field_check")) {
      const rawMoisture = sensorData?.soilMoisturePercent ?? sensorData?.soilMoisture ?? null;
      if (Number.isFinite(rawMoisture) && rawMoisture >= 38 && !validateSensor(sensorData, fieldContext).usable) {
        patched.action = "check field first";
        patched.fieldChecks = [...(patched.fieldChecks || []), "An older or unverified wet reading requires field verification before irrigating."];
        triggered.push("unverified_high_moisture_requires_field_check");
      }
    }
    if (fieldContext && !fieldContext.irrigationMethod && patched.action === "irrigate") {
      patched.action = "update missing data";
      triggered.push("missing_irrigation_method_blocks_irrigate");
    }
    if ((patched.confidenceScore || 0) < 0.45 && patched.action === "irrigate") {
      patched.action = "check field first";
      triggered.push("low_confidence_blocks_irrigate");
    }
    // Weather validation runs after the specific safety checks above so those named keys are always recorded.
    // missing, invalid, future-dated, stale, or expired weather must downgrade irrigate.
    const weatherCheck = validateWeather(weather);
    if (!weatherCheck.usable && patched.action === "irrigate") {
      patched.action = "check field first";
      patched.fieldChecks = [...(patched.fieldChecks || []), "Weather data must be refreshed before irrigation can be authorized."];
      triggered.push(weather.stale ? "stale_weather_downgrade_irrigate" : "weather_validation_failed_blocks_irrigate");
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
    else if (!weatherCheck.usable) warnings.push(`Weather data is not valid (${weatherCheck.reason}). Refresh before acting.`);
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
