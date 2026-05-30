export const weatherRiskAgent = {
  assess(weather = {}) {
    const risks = [];
    if (weather.heatRisk === "elevated" || weather.heatRisk === "high") risks.push("heat_risk");
    if (weather.frostRisk === "elevated" || weather.frostRisk === "high") risks.push("frost_risk");
    if ((weather.rainChance || 0) > 55) risks.push("rain_likely");
    return { risks, stale: Boolean(weather.stale) };
  },
};
