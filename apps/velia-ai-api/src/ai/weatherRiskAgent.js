export const weatherRiskAgent = {
  assess(weather = {}) {
    const risks = [];
    if (weather.heatRisk === "elevated") risks.push("heat_risk");
    if (weather.frostRisk === "elevated") risks.push("frost_risk");
    if ((weather.rainChance || 0) > 55) risks.push("rain_likely");
    return { risks, stale: Boolean(weather.stale) };
  },
};
