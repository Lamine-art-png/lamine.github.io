import { LLMProvider } from "./LLMProvider.js";
import { EmbeddingProvider } from "./EmbeddingProvider.js";
import { VectorStoreProvider } from "./VectorStoreProvider.js";
import { WeatherProvider } from "./WeatherProvider.js";
import { TranslationProvider } from "./TranslationProvider.js";
import { SatelliteProvider } from "./SatelliteProvider.js";

export class MockLLMProvider extends LLMProvider {
  constructor(name = "mock", options = {}) {
    super(name, { ...options, mode: options.mode || "mock", model: options.model || "mock-structured-decision" });
  }

  async generate(_prompt, options = {}) {
    if (options.schema) {
      return {
        text: JSON.stringify({
          action: "check field first",
          timing: "Today before evening",
          urgency: "medium",
          estimatedDurationRange: "0-30 min check",
          reasons: ["Local deterministic signals were used because no live reasoning provider is configured."],
          uncertainties: ["Live model unavailable; recommendation depends on field checks."],
          missingData: options.fallbackDecision?.missingData || [],
          fieldChecks: ["Check topsoil moisture", "Inspect leaf stress", "Confirm recent irrigation log"],
          risks: options.fallbackDecision?.risks || [],
          nextBestAction: "Update field condition after the check.",
          safetyNotes: ["Recommendation support only; validate in-field conditions."],
          verificationPlan: ["Log the action taken", "Capture field condition after action"],
        }),
        provider: this.name,
        model: this.model,
        mode: this.mode,
      };
    }
    return { text: "Local fallback response generated from structured context.", provider: this.name, model: this.model, mode: this.mode };
  }
}

export class AnthropicProvider extends LLMProvider {
  constructor(name = "anthropic", options = {}) {
    super(name, { ...options, mode: "placeholder", model: options.model || "future-anthropic-adapter", fallbackReason: "Anthropic adapter placeholder only" });
  }

  async generate() {
    throw new Error("Anthropic provider is a future adapter placeholder");
  }
}

export class MockEmbeddingProvider extends EmbeddingProvider {
  constructor(name = "mock", options = {}) {
    super(name, { ...options, mode: options.mode || "mock", model: options.model || "mock-hash-embedding" });
    this.dimensions = options.dimensions || 64;
  }

  async embed(text) {
    const vector = new Array(this.dimensions).fill(0);
    const tokens = String(text || "").toLowerCase().split(/\W+/).filter(Boolean);
    tokens.forEach((token, index) => {
      let hash = 0;
      for (let i = 0; i < token.length; i += 1) hash = ((hash << 5) - hash + token.charCodeAt(i)) | 0;
      const slot = Math.abs(hash) % this.dimensions;
      vector[slot] += 1 + Math.min(6, token.length) / 10 + (index % 5) * 0.01;
    });
    const norm = Math.sqrt(vector.reduce((sum, n) => sum + n * n, 0)) || 1;
    return vector.map((n) => n / norm);
  }
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
  constructor(name = "mock", options = {}) {
    super(name, { ...options, mode: options.mode || "mock" });
  }

  async getContext(location) {
    const now = new Date().toISOString();
    return {
      location,
      temperature: 33,
      humidity: 36,
      wind: 12,
      precipitationProbability: 14,
      rainChance: 14,
      rainfallForecastMm: 1,
      forecastSummary: "Hot and dry",
      weatherTimestamp: now,
      lastUpdated: now,
      weatherSource: "mock",
      source: "mock",
      freshness: { ageMinutes: 0, maxAgeMinutes: 45 },
      stale: false,
      heatRisk: "elevated",
      frostRisk: "low",
      evapotranspiration: 5.2,
      etLabel: "mock estimate",
    };
  }
}
export class GoogleWeatherProvider extends WeatherProvider {}

export class MockTranslationProvider extends TranslationProvider {
  async translate(text, language = "en") { return language === "en" ? text : `[${language}] ${text}`; }
}

export class MockSatelliteProvider extends SatelliteProvider {}
