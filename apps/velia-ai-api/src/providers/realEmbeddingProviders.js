import { EmbeddingProvider } from "./EmbeddingProvider.js";
import { fetchJsonWithRetry } from "../services/httpClient.js";

function assertVector(vector, providerName) {
  if (!Array.isArray(vector) || vector.length === 0 || vector.some((n) => typeof n !== "number" || Number.isNaN(n))) {
    throw new Error(`${providerName} embedding response did not contain a numeric vector`);
  }
  return vector;
}

export class OpenAIEmbeddingProvider extends EmbeddingProvider {
  constructor(options = {}) {
    super("openai", { model: options.model, mode: options.apiKey ? "live" : "mock", fallbackReason: options.apiKey ? null : "OPENAI_API_KEY not configured" });
    this.apiKey = options.apiKey || "";
    this.timeoutMs = options.timeoutMs;
    this.retries = options.retries;
    this.fetchImpl = options.fetchImpl;
  }

  async embed(text) {
    if (!this.apiKey) throw new Error("OPENAI_API_KEY not configured");
    const response = await fetchJsonWithRetry("https://api.openai.com/v1/embeddings", {
      method: "POST",
      headers: {
        authorization: `Bearer ${this.apiKey}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ model: this.model, input: String(text || " "), encoding_format: "float" }),
      timeoutMs: this.timeoutMs,
      retries: this.retries,
      fetchImpl: this.fetchImpl,
    });
    return assertVector(response?.data?.[0]?.embedding, "OpenAI");
  }
}

export class GeminiEmbeddingProvider extends EmbeddingProvider {
  constructor(options = {}) {
    super("gemini", { model: options.model || "gemini-embedding-2", mode: options.apiKey ? "live" : "mock", fallbackReason: options.apiKey ? null : "GEMINI_API_KEY not configured" });
    this.apiKey = options.apiKey || "";
    this.defaultTaskType = options.taskType || "RETRIEVAL_DOCUMENT";
    this.timeoutMs = options.timeoutMs;
    this.retries = options.retries;
    this.fetchImpl = options.fetchImpl;
  }

  isGeminiEmbedding2() {
    return this.model.includes("gemini-embedding-2");
  }

  async embed(text, options = {}) {
    if (!this.apiKey) throw new Error("GEMINI_API_KEY not configured");
    const taskType = options.taskType || this.defaultTaskType;
    const modelName = this.model.startsWith("models/") ? this.model : `models/${this.model}`;
    let requestBody;
    if (this.isGeminiEmbedding2()) {
      let finalText = String(text || " ");
      if (taskType === "RETRIEVAL_DOCUMENT") {
        finalText = `title: ${options.title || "none"} | text: ${finalText}`;
      } else if (taskType === "RETRIEVAL_QUERY") {
        finalText = `task: search result | query: ${finalText}`;
      }
      requestBody = { model: modelName, content: { parts: [{ text: finalText }] } };
    } else {
      const titlePrefix = options.title ? `${options.title}\n` : "";
      const finalText = `${titlePrefix}${String(text || " ")}`;
      requestBody = { model: modelName, content: { parts: [{ text: finalText }] }, taskType };
    }
    const response = await fetchJsonWithRetry(`https://generativelanguage.googleapis.com/v1beta/${encodeURIComponent(modelName).replaceAll("%2F", "/")}:embedContent`, {
      method: "POST",
      headers: {
        "x-goog-api-key": this.apiKey,
        "content-type": "application/json",
      },
      body: JSON.stringify(requestBody),
      timeoutMs: this.timeoutMs,
      retries: this.retries,
      fetchImpl: this.fetchImpl,
    });
    return assertVector(response?.embedding?.values, "Gemini");
  }
}
