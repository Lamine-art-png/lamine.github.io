import { storage } from "./storage.js";
import { getWeatherAdapter, listWeatherAdapters } from "./weatherProviders/registry.js";
import { apiClient } from "./apiClient.js";

const WK = "weather_cache";

export const weatherService = {
  async getWeather({ location, forceRefresh = false, provider = "mock" } = {}) {
    const cached = storage.get(WK, null);
    if (!forceRefresh && cached) {
      return { ...cached, cached: true, stale: !navigator.onLine, provider: cached.provider || provider };
    }

    try {
      if (navigator.onLine) {
        const remote = await apiClient.getWeatherContext({ location });
        const enrichedRemote = { ...remote, provider: remote.provider || "api" };
        storage.set(WK, enrichedRemote);
        return { ...enrichedRemote, cached: false, stale: false };
      }
    } catch {
      // fallback to local provider adapter
    }

    const adapter = getWeatherAdapter(provider);
    const current = await adapter.getCurrentWeather(location);
    const enriched = { ...current, provider };
    storage.set(WK, enriched);
    return { ...enriched, cached: false, stale: false };
  },
  getCachedWeather() {
    return storage.get(WK, null);
  },
  listProviders() {
    return listWeatherAdapters();
  },
};
