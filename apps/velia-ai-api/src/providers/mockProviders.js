import { LLMProvider } from "./LLMProvider.js";
import { EmbeddingProvider } from "./EmbeddingProvider.js";
import { VectorStoreProvider } from "./VectorStoreProvider.js";
import { WeatherProvider } from "./WeatherProvider.js";
import { TranslationProvider } from "./TranslationProvider.js";
import { SatelliteProvider } from "./SatelliteProvider.js";

async function safeJson(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

export class MockLLMProvider extends LLMProvider {
  async generate(prompt, options = {}) {
    return {
      text: `Mock response for ${options.task || "reasoning"}`,
      promptPreview: String(prompt).slice(0, 120),
      provider: "mock",
      model: options.model || "mock-model",
      fallback: true,
    };
  }
}

export class OpenAIProvider extends LLMProvider {
  async generate(prompt, options = {}) {
    if (!process.env.OPENAI_API_KEY) return new MockLLMProvider("mock").generate(prompt, options);

    const model = options.model || "gpt-4.1-mini";
    const response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${process.env.OPENAI_API_KEY}`,
      },
      body: JSON.stringify({
        model,
        messages: [{ role: "user", content: String(prompt) }],
        temperature: options.temperature ?? 0.2,
      }),
    });

    if (!response.ok) {
      const body = await safeJson(response);
      return {
        ...(await new MockLLMProvider("mock").generate(prompt, options)),
        error: body?.error?.message || `openai_http_${response.status}`,
      };
    }

    const body = await response.json();
    return {
      text: body?.choices?.[0]?.message?.content || "",
      provider: "openai",
      model,
      usage: body?.usage,
      fallback: false,
    };
  }
}

export class GeminiProvider extends LLMProvider {
  async generate(prompt, options = {}) {
    if (!process.env.GEMINI_API_KEY) return new MockLLMProvider("mock").generate(prompt, options);

    const model = options.model || "gemini-1.5-flash";
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${process.env.GEMINI_API_KEY}`;

    const response = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        contents: [{ parts: [{ text: String(prompt) }] }],
        generationConfig: { temperature: options.temperature ?? 0.2 },
      }),
    });

    if (!response.ok) {
      const body = await safeJson(response);
      return {
        ...(await new MockLLMProvider("mock").generate(prompt, options)),
        error: body?.error?.message || `gemini_http_${response.status}`,
      };
    }

    const body = await response.json();
    return {
      text: body?.candidates?.[0]?.content?.parts?.[0]?.text || "",
      provider: "gemini",
      model,
      usage: body?.usageMetadata,
      fallback: false,
    };
  }
}

export class AnthropicProvider extends LLMProvider {
  async generate(prompt, options = {}) {
    if (!process.env.ANTHROPIC_API_KEY) return new MockLLMProvider("mock").generate(prompt, options);

    const model = options.model || "claude-3-5-haiku-latest";
    const response = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": process.env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model,
        max_tokens: options.maxTokens || 512,
        temperature: options.temperature ?? 0.2,
        messages: [{ role: "user", content: String(prompt) }],
      }),
    });

    if (!response.ok) {
      const body = await safeJson(response);
      return {
        ...(await new MockLLMProvider("mock").generate(prompt, options)),
        error: body?.error?.message || `anthropic_http_${response.status}`,
      };
    }

    const body = await response.json();
    return {
      text: body?.content?.[0]?.text || "",
      provider: "anthropic",
      model,
      usage: body?.usage,
      fallback: false,
    };
  }
}

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
