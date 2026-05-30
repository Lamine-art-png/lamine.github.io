import fs from "fs";
import path from "path";
import { WeatherProvider } from "./WeatherProvider.js";
import { MockWeatherProvider } from "./mockProviders.js";
import { fetchJsonWithRetry } from "../services/httpClient.js";
import { config } from "../config.js";

const CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather";
const FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast";

function readCache(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return {};
  }
}

function writeCache(filePath, cache) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(cache, null, 2));
}

function ageMinutes(ts) {
  if (!ts) return Infinity;
  return Math.max(0, Math.round((Date.now() - new Date(ts).getTime()) / 60000));
}

function riskLabelHeat(tempC) {
  if (typeof tempC !== "number") return "unknown";
  if (tempC >= 35) return "high";
  if (tempC >= 32) return "elevated";
  return "low";
}

function riskLabelFrost(tempC) {
  if (typeof tempC !== "number") return "unknown";
  if (tempC <= 1) return "high";
  if (tempC <= 3) return "elevated";
  return "low";
}

function cacheKey({ lat, lon, location }) {
  if (lat != null && lon != null) return `${Number(lat).toFixed(4)},${Number(lon).toFixed(4)}`;
  return String(location || "unknown").toLowerCase();
}

function normalizeOpenWeather({ current, forecast, location, lat, lon, ttlMinutes }) {
  const currentMain = current?.main || {};
  const currentWind = current?.wind || {};
  const forecastRows = Array.isArray(forecast?.list) ? forecast.list : [];
  const nowSeconds = Math.floor(Date.now() / 1000);
  const next24h = forecastRows.filter((row) => typeof row.dt === "number" && row.dt <= nowSeconds + 24 * 3600);
  const relevantRows = next24h.length ? next24h : forecastRows.slice(0, 8);
  const precipitationProbability = Math.round(Math.max(0, ...relevantRows.map((row) => Number(row.pop || 0))) * 100);
  const rainfallForecastMm = relevantRows.reduce((sum, row) => sum + Number(row?.rain?.["3h"] || 0), Number(current?.rain?.["1h"] || 0));
  const summaryParts = [
    current?.weather?.[0]?.description,
    rainfallForecastMm >= 3 ? `${rainfallForecastMm.toFixed(1)} mm rain possible in next 24 hours` : "little rain expected in next 24 hours",
  ].filter(Boolean);
  const weatherTimestamp = current?.dt ? new Date(current.dt * 1000).toISOString() : new Date().toISOString();
  const freshnessAge = ageMinutes(weatherTimestamp);
  const stale = freshnessAge > ttlMinutes;
  const temperature = typeof currentMain.temp === "number" ? currentMain.temp : null;

  return {
    location: location || current?.name || `${lat},${lon}`,
    lat: lat ?? current?.coord?.lat ?? null,
    lon: lon ?? current?.coord?.lon ?? null,
    temperature,
    humidity: typeof currentMain.humidity === "number" ? currentMain.humidity : null,
    wind: typeof currentWind.speed === "number" ? currentWind.speed : null,
    precipitationProbability,
    rainChance: precipitationProbability,
    rainfallForecastMm: Number(rainfallForecastMm.toFixed(1)),
    forecastSummary: summaryParts.join("; ") || "Weather retrieved from OpenWeather.",
    weatherTimestamp,
    lastUpdated: weatherTimestamp,
    weatherSource: "openweather",
    source: "openweather",
    freshness: { ageMinutes: freshnessAge, maxAgeMinutes: ttlMinutes },
    stale,
    heatRisk: riskLabelHeat(temperature),
    frostRisk: riskLabelFrost(temperature),
    evapotranspiration: null,
    etLabel: "not provided by OpenWeather",
  };
}

export class OpenWeatherProvider extends WeatherProvider {
  constructor(options = {}) {
    super("openweather", { mode: options.apiKey ? "live" : "mock", fallbackReason: options.apiKey ? null : "OPENWEATHER_API_KEY not configured" });
    this.apiKey = options.apiKey || "";
    this.timeoutMs = options.timeoutMs || config.providerTimeoutMs;
    this.retries = options.retries ?? config.providerRetryCount;
    this.cacheFile = options.cacheFile || config.weatherCacheFile;
    this.ttlMinutes = options.ttlMinutes || config.weatherCacheTtlMinutes;
    this.fetchImpl = options.fetchImpl;
    this.mock = options.mock || new MockWeatherProvider();
  }

  async getContext(input = {}) {
    const locationInput = typeof input === "string" ? { location: input } : input;
    const lat = locationInput.lat ?? locationInput.latitude ?? locationInput.coordinates?.lat ?? null;
    const lon = locationInput.lon ?? locationInput.longitude ?? locationInput.coordinates?.lon ?? null;
    const location = locationInput.location || (lat != null && lon != null ? `${lat},${lon}` : "farm");
    const key = cacheKey({ lat, lon, location });

    if (!this.apiKey || lat == null || lon == null) {
      return {
        ...(await this.mock.getContext(location)),
        providerMode: "mock",
        fallbackStatus: !this.apiKey ? "missing_openweather_key" : "missing_coordinates",
      };
    }

    const params = new URLSearchParams({ lat: String(lat), lon: String(lon), units: "metric", appid: this.apiKey });
    try {
      const [current, forecast] = await Promise.all([
        fetchJsonWithRetry(`${CURRENT_URL}?${params.toString()}`, {
          timeoutMs: this.timeoutMs,
          retries: this.retries,
          fetchImpl: this.fetchImpl,
        }),
        fetchJsonWithRetry(`${FORECAST_URL}?${params.toString()}`, {
          timeoutMs: this.timeoutMs,
          retries: this.retries,
          fetchImpl: this.fetchImpl,
        }),
      ]);
      const normalized = normalizeOpenWeather({ current, forecast, location, lat, lon, ttlMinutes: this.ttlMinutes });
      const cache = readCache(this.cacheFile);
      cache[key] = { ...normalized, cachedAt: new Date().toISOString() };
      writeCache(this.cacheFile, cache);
      return { ...normalized, providerMode: "live", cached: false };
    } catch (error) {
      const cached = readCache(this.cacheFile)[key];
      if (cached) {
        const cachedAge = ageMinutes(cached.weatherTimestamp || cached.cachedAt);
        return {
          ...cached,
          cached: true,
          stale: true,
          freshness: { ageMinutes: cachedAge, maxAgeMinutes: this.ttlMinutes },
          providerMode: "stale-cache",
          fallbackStatus: "openweather_unavailable_stale_cache",
        };
      }
      return {
        ...(await this.mock.getContext(location)),
        providerMode: "mock",
        fallbackStatus: "openweather_unavailable_no_cache",
      };
    }
  }
}

export { normalizeOpenWeather };
