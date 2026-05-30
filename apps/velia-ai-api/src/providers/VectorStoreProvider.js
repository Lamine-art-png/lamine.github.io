export class VectorStoreProvider {
  constructor(name = "memory") { this.name = name; }
  async upsert(_doc) { throw new Error("VectorStoreProvider.upsert not implemented"); }
  async upsertMany(docs = []) {
    for (const doc of docs) await this.upsert(doc);
  }
  async search(_vector, _topK = 5) { throw new Error("VectorStoreProvider.search not implemented"); }
}

export class ProductionVectorStoreProvider extends VectorStoreProvider {
  constructor(name = "production-vector-placeholder") {
    super(name);
  }

  async upsert() {
    throw new Error("Production vector store is not provisioned. Use Postgres + pgvector or a managed vector database.");
  }

  async search() {
    throw new Error("Production vector store is not provisioned. Use Postgres + pgvector or a managed vector database.");
  }
}
