export function generateRecommendation(field, weather, context = {}) {
  const hoursSinceIrrigation = field.lastIrrigationAt
    ? Math.round((Date.now() - new Date(field.lastIrrigationAt).getTime()) / 3600000)
    : null;

  const missingData = [];
  if (!field.soilType) missingData.push("soil type");
  if (!field.lastIrrigationAt) missingData.push("last irrigation date");
  if (!field.dataSource || field.dataSource === "neither") missingData.push("sensor or controller data");
  if (!weather) missingData.push("weather update");

  const observation = context.lastObservation || field.lastObservation;
  const obsDry = observation === "Looks dry" || observation === "Leaves look stressed";
  const obsWet = observation === "Looks too wet";

  let score = 0;
  if (hoursSinceIrrigation && hoursSinceIrrigation > 72) score += 2;
  if (weather?.heatRisk === "elevated") score += 2;
  if ((weather?.rainfallForecastMm || 0) >= 6) score -= 2;
  if (obsDry) score += 2;
  if (obsWet) score -= 2;

  const urgency = score >= 4 ? "high" : score >= 2 ? "medium" : "low";
  const confidence = missingData.length >= 2 ? "moderate" : "high";

  const mainRecommendation =
    urgency === "high"
      ? `Check ${field.name} today before irrigating. Heat risk is elevated and water demand may be high.`
      : urgency === "medium"
        ? `Inspect ${field.name} today and irrigate only if topsoil is dry.`
        : `No urgent irrigation needed today for ${field.name}. Keep monitoring field condition.`;

  const reasonSummary = [
    `Crop: ${field.crop}`,
    `Weather: ${weather?.forecastSummary || "using last available weather data"}`,
    hoursSinceIrrigation ? `Last irrigation: ${Math.round(hoursSinceIrrigation / 24)} day(s) ago` : "Last irrigation not logged",
    observation ? `Field condition: ${observation}` : "No recent field observation",
  ];

  return {
    mainRecommendation,
    timing: urgency === "high" ? "Next 2-4 hours" : "Today before evening",
    urgency,
    confidence,
    reasonSummary,
    missingData,
    riskFlags: [weather?.heatRisk === "elevated" ? "heat_risk" : "", weather?.frostRisk === "elevated" ? "frost_risk" : ""].filter(Boolean),
    nextBestAction: missingData.length ? "Add a field condition update to improve confidence." : "Log irrigation or confirm no action needed.",
    generatedAt: new Date().toISOString(),
  };
}
