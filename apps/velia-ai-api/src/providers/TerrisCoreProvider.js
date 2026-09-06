import { LLMProvider } from "./LLMProvider.js";
import { fetchJsonWithRetry } from "../services/httpClient.js";

function normalizeBaseUrl(url = "") {
  return String(url || "").trim().replace(/\/+$/, "");
}

export class TerrisCoreProvider extends LLMProvider {
  constructor(options = {}) {
    const enabled = Boolean(options.enabled);
    const baseUrl = normalizeBaseUrl(options.baseUrl);
    const configured = enabled && Boolean(baseUrl);
    super("terris", {
      model: options.model || "terris-core-v0",
      mode: configured ? "live" : "mock",
      fallbackReason: configured ? null : (!enabled ? "TERRIS_CORE_ENABLED is false" : "TERRIS_CORE_BASE_URL not configured"),
    });
    this.baseUrl = baseUrl;
    this.apiKey = options.apiKey || "";
    this.timeoutMs = options.timeoutMs;
    this.retries = options.retries;
    this.fetchImpl = options.fetchImpl;
  }

  async generate(prompt, options = {}) {
    if (!this.isConfigured()) throw new Error(this.fallbackReason || "Terris Core is not configured");

    const systemParts = [
      options.system || "Return concise, grounded agricultural decision support.",
      "Preserve truth labels and provenance. Never invent measurements, execution, verification, regulatory approval, yields, or savings.",
      "Use deterministic tools for numeric agronomy and external truth when required.",
    ];
    if (options.schema) {
      systemParts.push("Return valid JSON matching this schema: " + JSON.stringify(options.schema));
    }

    const headers = { "content-type": "application/json" };
    if (this.apiKey) headers.authorization = "Bearer " + this.apiKey;

    const response = await fetchJsonWithRetry(this.baseUrl + "/v1/chat/completions", {
      method: "POST",
      headers,
      body: JSON.stringify({
        model: this.model,
        messages: [
          { role: "system", content: systemParts.join("\n") },
          { role: "user", content: String(prompt || "") },
        ],
        temperature: options.temperature ?? 0.1,
        max_tokens: options.maxOutputTokens || 1800,
      }),
      timeoutMs: this.timeoutMs,
      retries: this.retries,
      fetchImpl: this.fetchImpl,
    });

    const text = response?.choices?.[0]?.message?.content;
    if (typeof text !== "string" || !text.trim()) throw new Error("Terris Core response did not contain text output");

    return {
      text: text.trim(),
      provider: this.name,
      model: response?.model || this.model,
      mode: this.mode,
      rawProviderId: response?.id || null,
    };
  }
}
