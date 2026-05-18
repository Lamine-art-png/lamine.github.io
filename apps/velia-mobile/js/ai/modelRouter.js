const providers = ["gemini", "openai", "anthropic", "local"];

export const modelProfiles = {
  fastModel: { id: "fast-model", purpose: "translation/classification/extraction", providers },
  reasoningModel: { id: "reasoning-model", purpose: "irrigation decisions/planning", providers },
  visionModel: { id: "vision-model", purpose: "future field image analysis", providers },
  embeddingModel: { id: "embedding-model", purpose: "RAG embeddings", providers },
};

export const modelRouter = {
  route(taskType = "reasoning") {
    if (["translate", "classify", "extract"].includes(taskType)) return modelProfiles.fastModel;
    if (taskType === "vision") return modelProfiles.visionModel;
    if (taskType === "embed") return modelProfiles.embeddingModel;
    return modelProfiles.reasoningModel;
  },
  callMock(taskType, payload) {
    const profile = this.route(taskType);
    return {
      profile: profile.id,
      provider: "mock",
      taskType,
      output: {
        summary: `Mock ${taskType} response`,
        payload,
      },
      metadata: { ts: new Date().toISOString() },
    };
  },
};
