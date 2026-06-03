const WEATHER_FRESHNESS_CUTOFF_MINUTES = 90;

function weatherFreshnessScore(weather) {
  if (!weather || weather.stale) return 0;
  const ts = weather.weatherTimestamp || weather.lastUpdated;
  if (!ts) return 0;
  const ageMinutes = Math.max(0, (Date.now() - new Date(ts).getTime()) / 60000);
  if (ageMinutes <= 30) return 1;
  if (ageMinutes <= WEATHER_FRESHNESS_CUTOFF_MINUTES) return 0.6;
  return 0;
}

export function scoreEvidence(context = {}) {
  const evidenceChecked = [];
  const missingEvidence = [];
  const conflictingEvidence = [];
  let score = 0;
  let weight = 0;

  function add(label, points, total, present, conflictNote = null) {
    weight += total;
    if (present) {
      score += points;
      evidenceChecked.push(label);
    } else {
      missingEvidence.push(label);
    }
    if (conflictNote) conflictingEvidence.push(conflictNote);
  }

  const wFresh = weatherFreshnessScore(context.weather);
  add("weather freshness", wFresh * 12, 12, wFresh > 0);

  add("crop type", 8, 8, Boolean(context.crop));
  add("soil type", 7, 7, Boolean(context.soilType));
  add("irrigation method", 7, 7, Boolean(context.irrigationMethod));
  add("field coordinates", 4, 4, Boolean(context.coordinates || context.lat));

  const daysSinceIrrigation = context.lastIrrigationAt
    ? Math.max(0, (Date.now() - new Date(context.lastIrrigationAt).getTime()) / 86400000)
    : null;
  const recentLog = daysSinceIrrigation != null && daysSinceIrrigation < 14;
  add("recent irrigation log", recentLog ? 8 : 0, 8, recentLog, daysSinceIrrigation == null ? null : null);
  if (daysSinceIrrigation == null) missingEvidence.push("irrigation history");

  const hasObservation = Boolean(context.recentObservation || (context.observations || []).length > 0);
  add("recent field observation", 10, 10, hasObservation);

  const hasSensor = Boolean(context.sensorData || context.sensors);
  add("soil moisture sensor", hasSensor ? 10 : 0, 10, hasSensor);

  const hasController = Boolean(context.controllerStatus && context.controllerStatus !== "not connected");
  add("irrigation controller", hasController ? 6 : 0, 6, hasController);

  const hasEt = Boolean(context.weather?.evapotranspiration || context.weather?.etLabel && !context.weather.etLabel.includes("not provided"));
  add("ET source", hasEt ? 7 : 0, 7, hasEt);

  const hasSatellite = Boolean(context.satelliteEvidence || context.ndvi);
  add("satellite evidence", hasSatellite ? 5 : 0, 5, hasSatellite);

  const obsText = String(context.recentObservation || "").toLowerCase();
  const weatherWet = (context.weather?.rainChance || 0) >= 60 || (context.weather?.rainfallForecastMm || 0) >= 6;
  const obsDry = /dry|stress|wilting|crack/i.test(obsText);
  const obsWet = /too wet|standing water|saturated|waterlog/i.test(obsText);
  const sensorMoisture = context.sensorData?.soilMoisturePercent ?? context.sensorData?.soilMoisture ?? null;
  const sensorWet = typeof sensorMoisture === "number" && sensorMoisture >= 38;
  const sensorDry = typeof sensorMoisture === "number" && sensorMoisture <= 18;

  if (obsDry && weatherWet) conflictingEvidence.push("field observation says dry but rain is forecast");
  if (obsWet && sensorDry) conflictingEvidence.push("observation says too wet but sensor reports low moisture");
  if (obsDry && sensorWet) conflictingEvidence.push("observation says dry but sensor reports high moisture");
  if (conflictingEvidence.length > 0) {
    score = Math.max(0, score - conflictingEvidence.length * 6);
    weight += conflictingEvidence.length * 6;
  }

  const raw = weight > 0 ? score / weight : 0;
  const confidenceScore = Math.max(0.1, Math.min(0.95, raw));
  const confidenceLabel = confidenceScore >= 0.75 ? "high" : confidenceScore >= 0.5 ? "moderate" : "low";

  const improve = [];
  if (missingEvidence.includes("soil type")) improve.push("Add soil type to improve confidence.");
  if (missingEvidence.includes("crop type")) improve.push("Set crop type for better water demand estimates.");
  if (missingEvidence.includes("recent field observation")) improve.push("Record a field check observation.");
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
