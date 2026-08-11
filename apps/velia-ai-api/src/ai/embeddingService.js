import { modelRouter } from "./modelRouter.js";
import { MockEmbeddingProvider } from "../providers/mockProviders.js";

export const embeddingService = {
  async embed(text, options = {}) {
    const provider = modelRouter.embeddingProvider();
    try {
      const vector = await provider.embed(text, options);
      return { vector, model: provider.model || modelRouter.route("embed").id, provider: provider.name, providerMode: provider.mode, fallbackUsed: provider.mode !== "live" };
    } catch (error) {
      const fallback = new MockEmbeddingProvider("mock", { fallbackReason: error.message });
      const vector = await fallback.embed(text, options);
      return { vector, model: fallback.model, provider: fallback.name, providerMode: fallback.mode, fallbackUsed: true, fallbackReason: error.message };
    }
  },
};
