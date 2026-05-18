import { MockWeatherAdapter } from "./mockAdapter.js";

const adapters = {
  mock: new MockWeatherAdapter(),
};

export function getWeatherAdapter(provider = "mock") {
  return adapters[provider] || adapters.mock;
}

export function listWeatherAdapters() {
  return Object.keys(adapters);
}
