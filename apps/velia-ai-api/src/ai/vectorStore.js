import { config } from "../config.js";
import { LocalVectorStoreProvider } from "../providers/LocalVectorStoreProvider.js";
import { ProductionVectorStoreProvider } from "../providers/VectorStoreProvider.js";

function createVectorStore() {
  if (config.vectorProvider === "production" || config.vectorProvider === "pgvector" || config.vectorProvider === "managed") {
    return new ProductionVectorStoreProvider(config.vectorProvider);
  }
  return new LocalVectorStoreProvider({ filePath: config.vectorIndexFile });
}

export const vectorStore = createVectorStore();
