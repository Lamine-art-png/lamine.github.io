export class VectorStoreProvider {
  constructor(name = "memory") { this.name = name; }
  async upsert(_doc) { throw new Error("VectorStoreProvider.upsert not implemented"); }
  async search(_vector, _topK = 5) { throw new Error("VectorStoreProvider.search not implemented"); }
}
