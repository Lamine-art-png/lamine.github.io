export class EmbeddingProvider {
  constructor(name = "mock", options = {}) {
    this.name = name;
    this.model = options.model || name;
    this.mode = options.mode || "mock";
    this.fallbackReason = options.fallbackReason || null;
  }

  isConfigured() {
    return this.mode === "live";
  }

  async embed(_text) { throw new Error("EmbeddingProvider.embed not implemented"); }
}
