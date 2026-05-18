import { LLMProvider } from "./LLMProvider.js";
import { EmbeddingProvider } from "./EmbeddingProvider.js";
import { VectorStoreProvider } from "./VectorStoreProvider.js";
import { WeatherProvider } from "./WeatherProvider.js";
import { TranslationProvider } from "./TranslationProvider.js";
import { SatelliteProvider } from "./SatelliteProvider.js";

export class MockLLMProvider extends LLMProvider {
  async generate(prompt, options = {}) { return { text: `Mock response for ${options.task || "reasoning"}`, promptPreview: String(prompt).slice(0, 120) }; }
}
export class OpenAIProvider extends LLMProvider {}
export class GeminiProvider extends LLMProvider {}
export class AnthropicProvider extends LLMProvider {}

export class MockEmbeddingProvider extends EmbeddingProvider {
  async embed(text) { return String(text).split(/\W+/).filter(Boolean).slice(0, 24).map((t) => t.length / 10); }
}

export class InMemoryVectorProvider extends VectorStoreProvider {
  constructor() { super("memory"); this.rows = []; }
  async upsert(doc) { this.rows.push(doc); }
  async search(vector, topK = 5) {
    const score = (a, b) => a.reduce((acc, v, i) => acc + v * (b[i] || 0), 0) / Math.max(1, a.length);
    return this.rows.map((r) => ({ ...r, score: score(r.vector, vector) })).sort((a, b) => b.score - a.score).slice(0, topK);
  }
}

export class MockWeatherProvider extends WeatherProvider {
  async getContext(location) {
    return { location, temperature: 33, rainChance: 14, rainfallForecastMm: 1, humidity: 36, wind: 12, evapotranspiration: 5.2, heatRisk: "elevated", frostRisk: "low", forecastSummary: "Hot and dry", lastUpdated: new Date().toISOString(), stale: false, source: "mock" };
  }
}
export class OpenWeatherProvider extends WeatherProvider {}
export class GoogleWeatherProvider extends WeatherProvider {}

export class MockTranslationProvider extends TranslationProvider {
  async translate(text, language = "en") { return language === "en" ? text : `[${language}] ${text}`; }
}

export class MockSatelliteProvider extends SatelliteProvider {}
