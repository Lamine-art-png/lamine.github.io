import { fileURLToPath } from "url";
import { join, dirname } from "path";

// Absolute path to apps/velia-ai-api/src/storage/ — independent of process.cwd().
const _storageDir = join(dirname(fileURLToPath(import.meta.url)), "storage");

export function getConfig() {
  return {
    port: Number(process.env.PORT || 4310),
    corsOrigin: process.env.CORS_ORIGIN || "*",
    logLevel: process.env.LOG_LEVEL || "info",

    llmProvider: (process.env.LLM_PROVIDER || "mock").toLowerCase(),
    geminiApiKey: process.env.GEMINI_API_KEY || "",
    geminiModel: process.env.GEMINI_MODEL || "gemini-2.5-flash",
    openaiApiKey: process.env.OPENAI_API_KEY || "",
    openaiModel: process.env.OPENAI_MODEL || "gpt-4.1-mini",

    embeddingProvider: (process.env.EMBEDDING_PROVIDER || "mock").toLowerCase(),
    geminiEmbeddingModel: process.env.GEMINI_EMBEDDING_MODEL || "gemini-embedding-2",
    openaiEmbeddingModel: process.env.OPENAI_EMBEDDING_MODEL || "text-embedding-3-small",

    weatherProvider: (process.env.WEATHER_PROVIDER || "mock").toLowerCase(),
    openWeatherApiKey: process.env.OPENWEATHER_API_KEY || "",

    translationProvider: process.env.TRANSLATION_PROVIDER || "mock",
    vectorProvider: (process.env.VECTOR_PROVIDER || "local").toLowerCase(),
    memoryProvider: (process.env.MEMORY_PROVIDER || "json").toLowerCase(),
    memoryFile: process.env.MEMORY_FILE || join(_storageDir, "memory.json"),
    vectorIndexFile: process.env.VECTOR_INDEX_FILE || join(_storageDir, "vector-index.json"),
    weatherCacheFile: process.env.WEATHER_CACHE_FILE || join(_storageDir, "weather-cache.json"),

    providerTimeoutMs: Number(process.env.PROVIDER_TIMEOUT_MS || 12000),
    providerRetryCount: Number(process.env.PROVIDER_RETRY_COUNT || 2),
    weatherCacheTtlMinutes: Number(process.env.WEATHER_CACHE_TTL_MINUTES || 45),
  };
}

export const config = new Proxy({}, {
  get(_target, prop) {
    return getConfig()[prop];
  },
});
