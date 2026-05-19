export const weatherRiskAgent = {
  assess(weather) {
    const risks = [];
    if (!weather) return { risks: ["no_weather_data"], summary: "Weather unavailable" };
    if (weather.heatRisk === "elevated") risks.push("heat_risk");
    if (weather.frostRisk === "elevated") risks.push("frost_risk");
    if ((weather.rainChance || 0) > 55) risks.push("rain_likely");
    return {
      risks,
      summary: risks.length ? `Weather risks: ${risks.join(", ")}` : "No major weather risk",
      stale: Boolean(weather.stale),
    };
  },
};
