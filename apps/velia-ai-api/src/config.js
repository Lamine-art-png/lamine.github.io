export const config = {
  port: Number(process.env.PORT || 4310),
  corsOrigin: process.env.CORS_ORIGIN || "*",
  logLevel: process.env.LOG_LEVEL || "info",
  llmProvider: process.env.LLM_PROVIDER || "mock",
  embeddingProvider: process.env.EMBEDDING_PROVIDER || "mock",
  weatherProvider: process.env.WEATHER_PROVIDER || "mock",
  translationProvider: process.env.TRANSLATION_PROVIDER || "mock",
  vectorProvider: process.env.VECTOR_PROVIDER || "memory",
  memoryFile: process.env.MEMORY_FILE || "./src/storage/memory.json",
};
