import { modelRouter } from "./modelRouter.js";

export const embeddingService = {
  async embed(text) {
    const provider = modelRouter.embeddingProvider();
    const vector = await provider.embed(text);
    return { vector, model: modelRouter.route("embed").id };
  },
};
