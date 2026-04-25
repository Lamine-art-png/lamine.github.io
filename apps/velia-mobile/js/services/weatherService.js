import { storage } from "./storage.js";

const WK = "weather_cache";

function mockWeather(location = "unknown") {
  const hour = new Date().getHours();
  const temperature = hour > 13 ? 34 : 27;
  const rainChance = 18;
  const rainfallForecastMm = rainChance > 40 ? 8 : 1;
  const humidity = 38;
  const wind = 15;
  const evapotranspiration = 5.4;
  const heatRisk = temperature >= 33 ? "elevated" : "low";
  const frostRisk = temperature <= 3 ? "elevated" : "low";

  return {
    location,
    temperature,
    rainChance,
    rainfallForecastMm,
    wind,
    humidity,
    evapotranspiration,
    heatRisk,
    frostRisk,
    forecastSummary: heatRisk === "elevated" ? "Hot and dry with low chance of rain." : "Stable weather expected.",
    lastUpdated: new Date().toISOString(),
    source: "mock",
  };
}

export const weatherService = {
  async getWeather({ location, forceRefresh = false } = {}) {
    const cached = storage.get(WK, null);
    if (!forceRefresh && cached) {
      return { ...cached, cached: true, stale: !navigator.onLine };
    }
    const current = mockWeather(location);
    storage.set(WK, current);
    return { ...current, cached: false, stale: false };
  },
  getCachedWeather() {
    return storage.get(WK, null);
  },
};
