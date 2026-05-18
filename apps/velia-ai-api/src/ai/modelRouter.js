import { MockLLMProvider, OpenAIProvider, GeminiProvider, AnthropicProvider, MockEmbeddingProvider } from "../providers/mockProviders.js";
import { config } from "../config.js";

const llmProviders = {
  mock: new MockLLMProvider("mock"),
  openai: new OpenAIProvider("openai"),
  gemini: new GeminiProvider("gemini"),
  anthropic: new AnthropicProvider("anthropic"),
};

export const modelProfiles = {
  fastModel: { id: "fastModel", task: "classification/translation" },
  reasoningModel: { id: "reasoningModel", task: "decision reasoning" },
  visionModel: { id: "visionModel", task: "future vision analysis" },
  embeddingModel: { id: "embeddingModel", task: "RAG embeddings" },
};

export const modelRouter = {
  route(kind = "reasoning") {
    if (kind === "translate" || kind === "classify") return modelProfiles.fastModel;
    if (kind === "vision") return modelProfiles.visionModel;
    if (kind === "embed") return modelProfiles.embeddingModel;
    return modelProfiles.reasoningModel;
  },
  llmProvider() {
    return llmProviders[config.llmProvider] || llmProviders.mock;
  },
  embeddingProvider() {
    return new MockEmbeddingProvider();
  },
};
