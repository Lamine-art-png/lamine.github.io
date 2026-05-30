import { config } from "../config.js";
import { MockWeatherProvider } from "../providers/mockProviders.js";
import { OpenWeatherProvider } from "../providers/OpenWeatherProvider.js";
import { logProviderMode } from "./logger.js";

export function createWeatherProvider() {
  if (config.weatherProvider === "openweather") {
    const provider = config.openWeatherApiKey
      ? new OpenWeatherProvider({ apiKey: config.openWeatherApiKey })
      : new OpenWeatherProvider({ apiKey: "" });
    logProviderMode("weather", { provider: provider.name, mode: provider.mode, fallbackReason: provider.fallbackReason });
    return provider;
  }
  const provider = new MockWeatherProvider("mock", { fallbackReason: "WEATHER_PROVIDER is mock or unsupported" });
  logProviderMode("weather", { provider: provider.name, mode: provider.mode, fallbackReason: provider.fallbackReason });
  return provider;
}
