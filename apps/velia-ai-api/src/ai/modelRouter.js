import { AnthropicProvider, MockEmbeddingProvider, MockLLMProvider } from "../providers/mockProviders.js";
import { GeminiProvider, OpenAIProvider } from "../providers/realLLMProviders.js";
import { GeminiEmbeddingProvider, OpenAIEmbeddingProvider } from "../providers/realEmbeddingProviders.js";
import { TerrisCoreProvider } from "../providers/TerrisCoreProvider.js";
import { FailoverLLMProvider } from "../providers/FailoverLLMProvider.js";
import { config } from "../config.js";
import { logProviderMode } from "../services/logger.js";

export const modelProfiles = {
  fastModel: { id: "fastModel", task: "classification/translation" },
  reasoningModel: { id: "reasoningModel", task: "decision reasoning" },
  visionModel: { id: "visionModel", task: "future vision analysis" },
  embeddingModel: { id: "embeddingModel", task: "RAG embeddings" },
};

function makeMockLLM(reason) {
  return new MockLLMProvider("mock", { fallbackReason: reason });
}

function configuredFrontierProvider(requested) {
  if (requested === "openai" && config.openaiApiKey) {
    return new OpenAIProvider({
      apiKey: config.openaiApiKey,
      model: config.openaiModel,
      timeoutMs: config.providerTimeoutMs,
      retries: config.providerRetryCount,
    });
  }
  if (requested === "gemini" && config.geminiApiKey) {
    return new GeminiProvider({
      apiKey: config.geminiApiKey,
      model: config.geminiModel,
      timeoutMs: config.providerTimeoutMs,
      retries: config.providerRetryCount,
    });
  }
  return null;
}

function selectLLMProvider() {
  const requested = config.llmProvider;

  if (requested === "terris") {
    const terris = new TerrisCoreProvider({
      enabled: config.terrisCoreEnabled,
      baseUrl: config.terrisCoreBaseUrl,
      apiKey: config.terrisCoreApiKey,
      model: config.terrisCoreModel,
      timeoutMs: config.providerTimeoutMs,
      retries: config.providerRetryCount,
    });
    if (!terris.isConfigured()) {
      logProviderMode("llm", { provider: terris.name, mode: terris.mode, model: terris.model, fallbackReason: terris.fallbackReason });
      return makeMockLLM(terris.fallbackReason || "Terris Core is not configured");
    }

    const fallback = configuredFrontierProvider(config.terrisCoreFallbackProvider);
    const terrisSelected = !fallback
      || config.terrisCoreTrafficPercent >= 100
      || (config.terrisCoreTrafficPercent > 0 && Math.random() * 100 < config.terrisCoreTrafficPercent);

    if (!terrisSelected && fallback) {
      logProviderMode("llm", { provider: fallback.name, mode: fallback.mode, model: fallback.model, fallbackReason: "Terris Core rollout traffic split" });
      return fallback;
    }

    const provider = fallback ? new FailoverLLMProvider(terris, fallback) : terris;
    logProviderMode("llm", { provider: terris.name, mode: terris.mode, model: terris.model, fallbackReason: fallback ? "frontier failover armed" : null });
    return provider;
  }

  if (requested === "openai") {
    const provider = configuredFrontierProvider("openai") || makeMockLLM("OPENAI_API_KEY not configured");
    logProviderMode("llm", { provider: provider.name, mode: provider.mode, model: provider.model, fallbackReason: provider.fallbackReason });
    return provider;
  }
  if (requested === "gemini") {
    const provider = configuredFrontierProvider("gemini") || makeMockLLM("GEMINI_API_KEY not configured");
    logProviderMode("llm", { provider: provider.name, mode: provider.mode, model: provider.model, fallbackReason: provider.fallbackReason });
    return provider;
  }
  if (requested === "anthropic") {
    const provider = new AnthropicProvider();
    logProviderMode("llm", { provider: provider.name, mode: provider.mode, model: provider.model, fallbackReason: provider.fallbackReason });
    return makeMockLLM("Anthropic adapter is a future placeholder");
  }
  const provider = makeMockLLM("LLM_PROVIDER is mock or unsupported");
  logProviderMode("llm", { provider: provider.name, mode: provider.mode, model: provider.model, fallbackReason: provider.fallbackReason });
  return provider;
}

function selectEmbeddingProvider() {
  const requested = config.embeddingProvider;
  if (requested === "openai") {
    const provider = config.openaiApiKey
      ? new OpenAIEmbeddingProvider({ apiKey: config.openaiApiKey, model: config.openaiEmbeddingModel, timeoutMs: config.providerTimeoutMs, retries: config.providerRetryCount })
      : new MockEmbeddingProvider("mock", { fallbackReason: "OPENAI_API_KEY not configured" });
    logProviderMode("embedding", { provider: provider.name, mode: provider.mode, model: provider.model, fallbackReason: provider.fallbackReason });
    return provider;
  }
  if (requested === "gemini") {
    const provider = config.geminiApiKey
      ? new GeminiEmbeddingProvider({ apiKey: config.geminiApiKey, model: config.geminiEmbeddingModel, timeoutMs: config.providerTimeoutMs, retries: config.providerRetryCount })
      : new MockEmbeddingProvider("mock", { fallbackReason: "GEMINI_API_KEY not configured" });
    logProviderMode("embedding", { provider: provider.name, mode: provider.mode, model: provider.model, fallbackReason: provider.fallbackReason });
    return provider;
  }
  const provider = new MockEmbeddingProvider("mock", { fallbackReason: "EMBEDDING_PROVIDER is mock or unsupported" });
  logProviderMode("embedding", { provider: provider.name, mode: provider.mode, model: provider.model, fallbackReason: provider.fallbackReason });
  return provider;
}

export const modelRouter = {
  route(kind = "reasoning") {
    if (kind === "translate" || kind === "classify") return modelProfiles.fastModel;
    if (kind === "vision") return modelProfiles.visionModel;
    if (kind === "embed") return modelProfiles.embeddingModel;
    return modelProfiles.reasoningModel;
  },
  llmProvider() {
    return selectLLMProvider();
  },
  embeddingProvider() {
    return selectEmbeddingProvider();
  },
};
