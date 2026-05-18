export class EmbeddingProvider {
  constructor(name = "mock") { this.name = name; }
  async embed(_text) { throw new Error("EmbeddingProvider.embed not implemented"); }
}
