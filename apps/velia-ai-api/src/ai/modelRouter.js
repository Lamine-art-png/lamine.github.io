import { MockLLMProvider, OpenAIProvider, GeminiProvider, AnthropicProvider, MockEmbeddingProvider } from "../providers/mockProviders.js";
import { config } from "../config.js";

const llmProviders = {
  mock: new MockLLMProvider("mock"),
  openai: new OpenAIProvider("openai"),
  gemini: new GeminiProvider("gemini"),
  anthropic: new AnthropicProvider("anthropic"),
};

const hasKey = {
  openai: () => Boolean(process.env.OPENAI_API_KEY),
  gemini: () => Boolean(process.env.GEMINI_API_KEY),
  anthropic: () => Boolean(process.env.ANTHROPIC_API_KEY),
  mock: () => true,
};

function selectedProviderName() {
  const requested = (config.llmProvider || "mock").toLowerCase();
  if (requested !== "mock" && hasKey[requested]?.()) return requested;
  if (hasKey.openai()) return "openai";
  if (hasKey.gemini()) return "gemini";
  if (hasKey.anthropic()) return "anthropic";
  return "mock";
}

export const modelProfiles = {
  fastModel: {
    id: "fastModel",
    task: "fast_tasks",
    models: { openai: "gpt-4.1-mini", gemini: "gemini-1.5-flash", anthropic: "claude-3-5-haiku-latest", mock: "mock-fast" },
  },
  reasoningModel: {
    id: "reasoningModel",
    task: "reasoning_tasks",
    models: { openai: "gpt-4.1", gemini: "gemini-1.5-pro", anthropic: "claude-3-5-sonnet-latest", mock: "mock-reasoning" },
  },
  translationModel: {
    id: "translationModel",
    task: "translation_tasks",
    models: { openai: "gpt-4.1-mini", gemini: "gemini-1.5-flash", anthropic: "claude-3-5-haiku-latest", mock: "mock-translation" },
  },
  visionModel: { id: "visionModel", task: "future vision analysis" },
  embeddingModel: { id: "embeddingModel", task: "RAG embeddings" },
};

export const modelRouter = {
  route(kind = "reasoning") {
    if (kind === "translate") return modelProfiles.translationModel;
    if (kind === "fast" || kind === "classify") return modelProfiles.fastModel;
    if (kind === "vision") return modelProfiles.visionModel;
    if (kind === "embed") return modelProfiles.embeddingModel;
    return modelProfiles.reasoningModel;
  },
  llmProvider() {
    return llmProviders[selectedProviderName()] || llmProviders.mock;
  },
  modelFor(kind = "reasoning") {
    const profile = this.route(kind);
    const providerName = selectedProviderName();
    return profile.models?.[providerName] || profile.models?.mock || "mock-model";
  },
  embeddingProvider() {
    return new MockEmbeddingProvider();
  },
};
