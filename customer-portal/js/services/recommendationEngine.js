export const recommendationEngine = {
  generateRecommendation({ field, weather, crop }) {
    const hoursSinceIrrigation = Math.floor((Date.now() - new Date(field.lastIrrigationAt).getTime()) / 3600000);
    const hot = weather.temperatureC >= 33;
    const stressed = field.waterStressLevel === "high";
    const needsWater = stressed || hoursSinceIrrigation > 48 || hot;

    const confidence = stressed ? "high" : field.dataSourceStatus === "weather_only" ? "moderate" : "high";

    return {
      id: `rec-${field.id}`,
      fieldId: field.id,
      type: needsWater ? "irrigate_now" : "monitor",
      action: needsWater ? `Run ${field.irrigationMethod} cycle and verify moisture.` : "Continue monitoring and re-check in the evening.",
      timing: needsWater ? "Today, next 2-4 hours" : "Today, 18:00",
      confidence,
      reasoning: [
        `${crop?.name || "Crop"} stage: ${crop?.stage || "unknown"}`,
        `Weather: ${weather.summary}`,
        `Last irrigation: ${hoursSinceIrrigation}h ago`,
      ],
      riskFlags: [
        ...(hot ? ["heat_event"] : []),
        ...(stressed ? ["water_stress_risk"] : []),
        ...(field.dataSourceStatus === "manual" ? ["limited_sensor_coverage"] : []),
      ],
      createdAt: new Date().toISOString(),
    };
  },
};
