import { LLMProvider } from "./LLMProvider.js";
import { fetchJsonWithRetry } from "../services/httpClient.js";

function extractOpenAIText(response) {
  if (typeof response?.output_text === "string") return response.output_text;
  const pieces = [];
  for (const item of response?.output || []) {
    for (const content of item.content || []) {
      if (typeof content.text === "string") pieces.push(content.text);
      if (typeof content?.content === "string") pieces.push(content.content);
    }
  }
  return pieces.join("\n").trim();
}

function extractGeminiText(response) {
  return (response?.candidates || [])
    .flatMap((candidate) => candidate?.content?.parts || [])
    .map((part) => part.text || "")
    .join("\n")
    .trim();
}

export class OpenAIProvider extends LLMProvider {
  constructor(options = {}) {
    super("openai", { model: options.model, mode: options.apiKey ? "live" : "mock", fallbackReason: options.apiKey ? null : "OPENAI_API_KEY not configured" });
    this.apiKey = options.apiKey || "";
    this.timeoutMs = options.timeoutMs;
    this.retries = options.retries;
    this.fetchImpl = options.fetchImpl;
  }

  async generate(prompt, options = {}) {
    if (!this.apiKey) throw new Error("OPENAI_API_KEY not configured");
    const body = {
      model: this.model,
      input: [
        { role: "system", content: [{ type: "input_text", text: options.system || "Return concise, valid JSON for agricultural decision support." }] },
        { role: "user", content: [{ type: "input_text", text: String(prompt || "") }] },
      ],
      temperature: options.temperature ?? 0.2,
      max_output_tokens: options.maxOutputTokens || 1800,
    };
    if (options.schema) {
      body.text = {
        format: {
          type: "json_schema",
          name: options.schemaName || "terris_irrigation_decision",
          schema: options.schema,
          strict: true,
        },
      };
    }

    const response = await fetchJsonWithRetry("https://api.openai.com/v1/responses", {
      method: "POST",
      headers: {
        authorization: `Bearer ${this.apiKey}`,
        "content-type": "application/json",
      },
      body: JSON.stringify(body),
      timeoutMs: this.timeoutMs,
      retries: this.retries,
      fetchImpl: this.fetchImpl,
    });

    const text = extractOpenAIText(response);
    if (!text) throw new Error("OpenAI response did not contain text output");
    return { text, provider: this.name, model: this.model, mode: this.mode, rawProviderId: response?.id || null };
  }
}

export class GeminiProvider extends LLMProvider {
  constructor(options = {}) {
    super("gemini", { model: options.model, mode: options.apiKey ? "live" : "mock", fallbackReason: options.apiKey ? null : "GEMINI_API_KEY not configured" });
    this.apiKey = options.apiKey || "";
    this.timeoutMs = options.timeoutMs;
    this.retries = options.retries;
    this.fetchImpl = options.fetchImpl;
  }

  async generate(prompt, options = {}) {
    if (!this.apiKey) throw new Error("GEMINI_API_KEY not configured");
    const generationConfig = {
      temperature: options.temperature ?? 0.2,
      maxOutputTokens: options.maxOutputTokens || 1800,
    };
    if (options.schema) {
      generationConfig.responseMimeType = "application/json";
      generationConfig.responseJsonSchema = options.schema;
    }

    const response = await fetchJsonWithRetry(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(this.model)}:generateContent`, {
      method: "POST",
      headers: {
        "x-goog-api-key": this.apiKey,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        contents: [{
          role: "user",
          parts: [{ text: `${options.system || "Return valid JSON for agricultural decision support."}\n\n${String(prompt || "")}` }],
        }],
        generationConfig,
      }),
      timeoutMs: this.timeoutMs,
      retries: this.retries,
      fetchImpl: this.fetchImpl,
    });

    const text = extractGeminiText(response);
    if (!text) throw new Error("Gemini response did not contain text output");
    return { text, provider: this.name, model: this.model, mode: this.mode, rawProviderId: response?.responseId || null };
  }
}
