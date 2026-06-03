const WEATHER_FRESHNESS_CUTOFF_MINUTES = 90;
const CORE_MAX = 56;

function weatherFreshnessScore(weather) {
  if (!weather || weather.stale) return 0;
  const ts = weather.weatherTimestamp || weather.lastUpdated;
  if (!ts) return 0;
  const ageMinutes = Math.max(0, (Date.now() - new Date(ts).getTime()) / 60000);
  if (ageMinutes <= 30) return 1;
  if (ageMinutes <= WEATHER_FRESHNESS_CUTOFF_MINUTES) return 0.6;
  return 0;
}

function observationRecencyPoints(context) {
  const hasObs = Boolean(context.recentObservation || (context.observations || []).length > 0);
  if (!hasObs) return 0;
  const ts = context.observationTimestamp;
  if (!ts) return 6; // partial credit — timestamp unknown
  const ageMs = Date.now() - new Date(ts).getTime();
  if (!Number.isFinite(ageMs) || ageMs < 0) return 10;
  const ageDays = ageMs / 86400000;
  if (ageDays < 1) return 10;
  if (ageDays < 7) return 7;
  if (ageDays < 30) return 4;
  return 1;
}

export function scoreEvidence(context = {}) {
  const evidenceChecked = [];
  const missingEvidence = [];
  const conflictingEvidence = [];
  let coreScore = 0;

  const wFresh = weatherFreshnessScore(context.weather);
  const weatherPts = Math.round(wFresh * 12);
  if (weatherPts > 0) { coreScore += weatherPts; evidenceChecked.push("weather freshness"); }
  else missingEvidence.push("weather freshness");

  if (context.crop) { coreScore += 8; evidenceChecked.push("crop type"); }
  else missingEvidence.push("crop type");

  if (context.soilType) { coreScore += 7; evidenceChecked.push("soil type"); }
  else missingEvidence.push("soil type");

  if (context.irrigationMethod) { coreScore += 7; evidenceChecked.push("irrigation method"); }
  else missingEvidence.push("irrigation method");

  if (context.coordinates || context.lat) { coreScore += 4; evidenceChecked.push("field coordinates"); }
  else missingEvidence.push("field coordinates");

  const daysSinceIrrigation = context.lastIrrigationAt
    ? Math.max(0, (Date.now() - new Date(context.lastIrrigationAt).getTime()) / 86400000)
    : null;
  if (daysSinceIrrigation == null) {
    missingEvidence.push("irrigation history");
  } else if (daysSinceIrrigation < 14) {
    coreScore += 8;
    evidenceChecked.push("recent irrigation log");
  } else {
    missingEvidence.push("recent irrigation log");
  }

  const obsPts = observationRecencyPoints(context);
  if (obsPts > 0) {
    coreScore += obsPts;
    evidenceChecked.push("recent field observation");
    const hasObs = Boolean(context.recentObservation || (context.observations || []).length > 0);
    if (hasObs && !context.observationTimestamp) missingEvidence.push("observation timestamp");
  } else {
    missingEvidence.push("recent field observation");
  }

  // Optional precision boosters — additive, not penalized when absent
  let optionalBoost = 0;
  const sensorMoisture = context.sensorData?.soilMoisturePercent ?? context.sensorData?.soilMoisture ?? null;
  if (typeof sensorMoisture === "number") {
    optionalBoost += 0.10;
    evidenceChecked.push("soil moisture sensor");
  } else {
    missingEvidence.push("soil moisture sensor");
  }

  if (context.controllerStatus && context.controllerStatus !== "not connected") {
    optionalBoost += 0.07;
    evidenceChecked.push("irrigation controller");
  } else {
    missingEvidence.push("irrigation controller");
  }

  const hasEt = Boolean(context.weather?.evapotranspiration || (context.weather?.etLabel && !context.weather.etLabel.includes("not provided")));
  if (hasEt) {
    optionalBoost += 0.07;
    evidenceChecked.push("ET source");
  } else {
    missingEvidence.push("ET source");
  }

  const hasSatellite = Boolean(context.satelliteEvidence || context.ndvi != null);
  if (hasSatellite) {
    optionalBoost += 0.06;
    evidenceChecked.push("satellite evidence");
  } else {
    missingEvidence.push("satellite evidence");
  }

  const obsText = String(context.recentObservation || "").toLowerCase();
  const weatherWet = (context.weather?.rainChance || 0) >= 60 || (context.weather?.rainfallForecastMm || 0) >= 6;
  const obsDry = /dry|stress|wilting|crack/i.test(obsText);
  const obsWet = /too wet|standing water|saturated|waterlog/i.test(obsText);
  const sensorWet = typeof sensorMoisture === "number" && sensorMoisture >= 38;
  const sensorDry = typeof sensorMoisture === "number" && sensorMoisture <= 18;

  if (obsDry && weatherWet) conflictingEvidence.push("field observation says dry but rain is forecast");
  if (obsWet && sensorDry) conflictingEvidence.push("observation says too wet but sensor reports low moisture");
  if (obsDry && sensorWet) conflictingEvidence.push("observation says dry but sensor reports high moisture");

  const conflictPenalty = conflictingEvidence.length * 0.15;
  const raw = (coreScore / CORE_MAX) + Math.min(0.25, optionalBoost) - conflictPenalty;
  const confidenceScore = Math.max(0.1, Math.min(0.95, raw));
  const confidenceLabel = confidenceScore >= 0.75 ? "high" : confidenceScore >= 0.5 ? "moderate" : "low";

  const improve = [];
  if (missingEvidence.includes("soil type")) improve.push("Add soil type to improve confidence.");
  if (missingEvidence.includes("crop type")) improve.push("Set crop type for better water demand estimates.");
  if (missingEvidence.includes("recent field observation")) improve.push("Record a field check observation.");
  if (missingEvidence.includes("observation timestamp")) improve.push("Observation timestamp is unknown.");
  if (missingEvidence.includes("soil moisture sensor")) improve.push("Connect a soil sensor for measured moisture readings.");
  if (missingEvidence.includes("ET source")) improve.push("Enable an ET provider for evapotranspiration data.");
  if (missingEvidence.includes("satellite evidence")) improve.push("Satellite evidence is not available for this recommendation.");
  if (missingEvidence.includes("weather freshness")) improve.push("Refresh weather data before acting.");
  if (missingEvidence.includes("irrigation history")) improve.push("Log past irrigations to improve timing accuracy.");
  if (conflictingEvidence.length > 0) improve.push("Resolve conflicting field signals before irrigating.");

  const explanation = confidenceScore >= 0.75
    ? `Velia has strong evidence across ${evidenceChecked.length} sources including ${evidenceChecked.slice(0, 3).join(", ")}.`
    : confidenceScore >= 0.5
      ? `Velia has usable evidence but is missing ${missingEvidence.slice(0, 2).join(" and ")} which would improve certainty.`
      : `Velia has limited evidence (missing: ${missingEvidence.slice(0, 3).join(", ")}). Field check required before action.`;

  return {
    confidenceScore: Number(confidenceScore.toFixed(3)),
    confidenceLabel,
    evidenceChecked,
    missingEvidence,
    conflictingEvidence,
    explanation,
    improvementSuggestions: improve,
  };
}
