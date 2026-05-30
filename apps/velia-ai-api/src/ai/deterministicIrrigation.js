const soilModifiers = {
  sand: 0.1,
  sandy: 0.1,
  loam: 0,
  clay: -0.04,
};

const methodEfficiency = {
  drip: 0.9,
  sprinkler: 0.75,
  pivot: 0.78,
  flood: 0.55,
};

export function daysSince(dateValue) {
  if (!dateValue) return null;
  const ms = Date.now() - new Date(dateValue).getTime();
  if (!Number.isFinite(ms)) return null;
  return Math.max(0, ms / 86400000);
}

export function buildNormalizedFieldContext({ field = {}, weather = {}, logs = [], observations = [], memory = {} }) {
  const recentObservation = observations[0] || memory.recentObservations?.[0] || {};
  const lastLog = logs[0] || memory.recentLogs?.[0] || null;
  return {
    fieldId: field.id || field.fieldId || "unknown-field",
    name: field.name || "Field",
    crop: field.crop || null,
    acreage: field.acreage || field.area || null,
    soilType: field.soilType || null,
    irrigationMethod: field.irrigationMethod || null,
    dataSource: field.dataSource || field.hardware || "unknown",
    waterStressLevel: field.waterStressLevel || null,
    sensorData: field.sensorData || field.sensors || null,
    controllerStatus: field.controllerStatus || field.controller || null,
    lastIrrigationAt: field.lastIrrigationAt || lastLog?.performedAt || null,
    recentObservation: recentObservation.condition || recentObservation.note || field.lastObservation || null,
    weather,
    logs,
    observations,
    memory,
  };
}

function missingDataFor(ctx) {
  const missing = [];
  if (!ctx.crop) missing.push("crop");
  if (!ctx.soilType) missing.push("soil type");
  if (!ctx.irrigationMethod) missing.push("irrigation method");
  if (!ctx.lastIrrigationAt) missing.push("last irrigation");
  if (!ctx.recentObservation) missing.push("recent field observation");
  if (!ctx.weather || ctx.weather.stale || !ctx.weather.weatherTimestamp) missing.push("fresh weather");
  if (!ctx.sensorData && (!ctx.dataSource || ctx.dataSource === "neither" || ctx.dataSource === "manual")) missing.push("sensor or controller data");
  return [...new Set(missing)];
}

function observationSignal(observation) {
  if (/too wet|standing water|saturated|waterlog/i.test(observation || "")) return { delta: -0.35, rule: "wet_observation", label: "wet observation" };
  if (/dry|stress|wilting|crack/i.test(observation || "")) return { delta: 0.18, rule: "dry_observation", label: "dry observation" };
  return { delta: 0, rule: null, label: "no strong observation signal" };
}

function sensorSignal(sensorData) {
  const moisture = sensorData?.soilMoisturePercent ?? sensorData?.soilMoisture ?? null;
  if (typeof moisture !== "number") return { delta: 0, rule: null, label: "no soil moisture sensor value" };
  if (moisture <= 18) return { delta: 0.24, rule: "sensor_low_moisture", label: "sensor reports low moisture" };
  if (moisture >= 38) return { delta: -0.25, rule: "sensor_high_moisture", label: "sensor reports high moisture" };
  return { delta: 0.02, rule: "sensor_moderate_moisture", label: "sensor moisture is moderate" };
}

export function calculateDeterministicSignals(context) {
  const ctx = context;
  const rulesTriggered = [];
  const assumptions = [];
  const confidenceDrivers = [];
  const missingData = missingDataFor(ctx);
  let needScore = ctx.waterStressLevel === "high" ? 0.74 : ctx.waterStressLevel === "moderate" ? 0.56 : ctx.waterStressLevel === "low" ? 0.32 : 0.48;

  if (ctx.waterStressLevel) confidenceDrivers.push(`field stress level: ${ctx.waterStressLevel}`);
  else assumptions.push("No field water-stress setting; started from a moderate default.");

  const days = daysSince(ctx.lastIrrigationAt);
  if (days == null) assumptions.push("Last irrigation is unknown.");
  else if (days < 1) {
    needScore -= 0.22;
    rulesTriggered.push("recent_irrigation");
    confidenceDrivers.push("recent irrigation reduces urgency");
  } else if (days > 4) {
    needScore += 0.12;
    rulesTriggered.push("long_since_irrigation");
    confidenceDrivers.push("several days since irrigation");
  } else {
    confidenceDrivers.push(`${days.toFixed(1)} days since irrigation`);
  }

  const soilKey = String(ctx.soilType || "").toLowerCase();
  const soilDelta = Object.entries(soilModifiers).find(([key]) => soilKey.includes(key))?.[1] ?? 0;
  needScore += soilDelta;
  if (soilDelta !== 0) confidenceDrivers.push(`soil adjustment: ${ctx.soilType}`);

  const methodKey = String(ctx.irrigationMethod || "").toLowerCase();
  const efficiency = Object.entries(methodEfficiency).find(([key]) => methodKey.includes(key))?.[1] ?? null;
  if (efficiency) assumptions.push(`Irrigation method efficiency assumed around ${Math.round(efficiency * 100)}% for ${ctx.irrigationMethod}.`);
  else assumptions.push("No irrigation method efficiency assumption available.");

  const obs = observationSignal(ctx.recentObservation);
  needScore += obs.delta;
  if (obs.rule) {
    rulesTriggered.push(obs.rule);
    confidenceDrivers.push(obs.label);
  }

  const sensor = sensorSignal(ctx.sensorData);
  needScore += sensor.delta;
  if (sensor.rule) {
    rulesTriggered.push(sensor.rule);
    confidenceDrivers.push(sensor.label);
  }

  if (ctx.weather?.heatRisk === "high" || ctx.weather?.heatRisk === "elevated") {
    needScore += ctx.weather.heatRisk === "high" ? 0.15 : 0.1;
    rulesTriggered.push("heat_risk");
    confidenceDrivers.push(`heat risk: ${ctx.weather.heatRisk}`);
  }
  if (ctx.weather?.frostRisk === "high" || ctx.weather?.frostRisk === "elevated") {
    rulesTriggered.push("frost_risk");
    needScore -= 0.08;
  }
  if ((ctx.weather?.rainfallForecastMm || 0) >= 6 || (ctx.weather?.rainChance || 0) >= 60) {
    needScore -= 0.22;
    rulesTriggered.push("rain_likely");
    confidenceDrivers.push("rain forecast reduces irrigation urgency");
  }
  if (ctx.weather?.stale) {
    rulesTriggered.push("stale_weather");
    assumptions.push("Weather is stale; confidence is reduced and field checks are prioritized.");
  }

  needScore = Math.max(0.05, Math.min(0.95, needScore));
  const pressureLabel = needScore >= 0.72 ? "high" : needScore >= 0.45 ? "moderate" : "low";
  const action = needScore >= 0.72 ? "irrigate" : needScore >= 0.45 ? "check field first" : ((ctx.weather?.rainChance || 0) >= 60 ? "wait" : "monitor");
  const confidenceScore = Math.max(0.2, Math.min(0.95, needScore - missingData.length * 0.055 - (ctx.weather?.stale ? 0.12 : 0)));

  return {
    needScore,
    pressureLabel,
    action,
    urgency: needScore >= 0.72 ? "high" : needScore >= 0.45 ? "medium" : "low",
    confidenceScore,
    confidenceDrivers,
    missingData,
    rulesTriggered: [...new Set(rulesTriggered)],
    assumptions,
    estimatedWaterPressure: {
      label: pressureLabel,
      score: Number(needScore.toFixed(2)),
      assumptions,
      notExactEt: !ctx.weather?.evapotranspiration,
    },
  };
}

export function deterministicDecisionFromSignals(signals, context) {
  const action = signals.action;
  return {
    action,
    timing: action === "irrigate" ? "Next 2-4 hours after a field check" : action === "wait" ? "Recheck after forecast rain window" : "Today before evening",
    urgency: signals.urgency,
    estimatedDurationRange: action === "irrigate" ? "45-90 min, adjust to system flow and field check" : "0-30 min field check",
    reasons: [
      `Estimated water pressure is ${signals.pressureLabel} (${signals.needScore.toFixed(2)}) from field, weather, and observation signals.`,
      `Weather: ${context.weather?.forecastSummary || "not available"}`,
      `Recent field observation: ${context.recentObservation || "not available"}`,
    ],
    uncertainties: signals.missingData.length ? [`Missing ${signals.missingData.join(", ")}`] : ["No major missing-data driver found."],
    missingData: signals.missingData,
    fieldChecks: ["Check topsoil/root-zone moisture before acting", "Inspect leaves for stress or waterlogging", "Confirm recent irrigation log"],
    risks: signals.rulesTriggered.filter((rule) => rule.endsWith("_risk") || rule.includes("rain") || rule.includes("weather")),
    nextBestAction: action === "irrigate" ? "If field check confirms dryness, irrigate and log the duration." : "Update field condition to improve tomorrow's confidence.",
    safetyNotes: ["Recommendation support only; validate in-field conditions.", "No measured soil-moisture value is assumed without sensor data."],
    verificationPlan: ["Log whether irrigation happened", "Record duration if irrigated", "Capture a post-action field observation"],
  };
}
