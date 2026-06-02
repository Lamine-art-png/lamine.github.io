import { storage } from "./storage.js";
import { getWeatherAdapter, listWeatherAdapters } from "./weatherProviders/registry.js";
import { apiClient } from "./apiClient.js";

const WK = "weather_cache";
export const WEATHER_CACHE_TTL_MS = 20 * 60 * 1000;

function weatherTimestampOf(weather) {
  return weather?.weatherTimestamp || weather?.lastUpdated || weather?.cachedAt || null;
}

function ageMinutes(weather, now = Date.now()) {
  const ts = weatherTimestampOf(weather);
  if (!ts) return null;
  const age = Math.max(0, Math.round((now - new Date(ts).getTime()) / 60000));
  return Number.isFinite(age) ? age : null;
}

function withCacheMetadata(weather, { cached, stale, provider, fallbackStatus } = {}) {
  const age = ageMinutes(weather);
  return {
    ...weather,
    provider: weather?.provider || provider,
    cached,
    stale: Boolean(stale ?? weather?.stale),
    freshness: weather?.freshness || (age == null ? undefined : { ageMinutes: age }),
    weatherTimestamp: weather?.weatherTimestamp || weather?.lastUpdated || weather?.cachedAt,
    fallbackStatus: weather?.fallbackStatus || fallbackStatus,
  };
}

export const weatherService = {
  async getWeather({ location, coordinates = null, forceRefresh = false, provider = "mock" } = {}) {
    const cached = storage.get(WK, null);
    const cachedAge = cached ? ageMinutes(cached) : null;
    const cacheFresh = cachedAge != null && cachedAge * 60000 <= WEATHER_CACHE_TTL_MS;
    if (!forceRefresh && cached && cacheFresh && navigator.onLine) {
      return withCacheMetadata(cached, { cached: true, stale: cached.stale, provider: cached.provider || provider });
    }
    if (!navigator.onLine && cached) {
      return withCacheMetadata(cached, {
        cached: true,
        stale: true,
        provider: cached.provider || provider,
        fallbackStatus: cached.fallbackStatus || "offline cached weather",
      });
    }

    try {
      if (navigator.onLine) {
        const remote = await apiClient.getWeatherContext({ location, coordinates, lat: coordinates?.lat, lon: coordinates?.lon });
        const enrichedRemote = {
          ...remote,
          provider: remote.provider || "api",
          cachedAt: new Date().toISOString(),
          weatherTimestamp: remote.weatherTimestamp || remote.lastUpdated || remote.cachedAt || new Date().toISOString(),
        };
        storage.set(WK, enrichedRemote);
        return withCacheMetadata(enrichedRemote, { cached: false, stale: remote.stale, provider: enrichedRemote.provider });
      }
    } catch {
      // fallback to local provider adapter
    }

    if (!forceRefresh && cached) {
      return withCacheMetadata(cached, {
        cached: true,
        stale: true,
        provider: cached.provider || provider,
        fallbackStatus: cached.fallbackStatus || "expired cached weather",
      });
    }

    const adapter = getWeatherAdapter(provider);
    const current = await adapter.getCurrentWeather(location);
    const enriched = {
      ...current,
      provider,
      cachedAt: new Date().toISOString(),
      weatherTimestamp: current.weatherTimestamp || current.lastUpdated || new Date().toISOString(),
      fallbackStatus: current.fallbackStatus || "local weather fallback",
    };
    storage.set(WK, enriched);
    return withCacheMetadata(enriched, { cached: false, stale: current.stale, provider });
  },
  getCachedWeather() {
    return storage.get(WK, null);
  },
  listProviders() {
    return listWeatherAdapters();
  },
};
