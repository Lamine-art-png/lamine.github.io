import { config } from "../config.js";
import { LocalVectorStoreProvider } from "../providers/LocalVectorStoreProvider.js";
import { ProductionVectorStoreProvider } from "../providers/VectorStoreProvider.js";

function createVectorStore() {
  if (config.vectorProvider === "production" || config.vectorProvider === "pgvector" || config.vectorProvider === "managed") {
    return new ProductionVectorStoreProvider(config.vectorProvider);
  }
  return new LocalVectorStoreProvider({ filePath: config.vectorIndexFile });
}

// Lazy singleton — config (including VECTOR_INDEX_FILE) is read on first use, not at module eval.
let _instance = null;
export const vectorStore = new Proxy({}, {
  get(_t, prop) {
    if (!_instance) _instance = createVectorStore();
    return _instance[prop];
  },
});
