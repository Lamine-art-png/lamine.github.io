export function getConfig() {
  const env = (terrisName, legacyName, fallback = "") => process.env[terrisName] ?? process.env[legacyName] ?? fallback;
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
    geminiEmbeddingModel: process.env.GEMINI_EMBEDDING_MODEL || "text-embedding-004",
    openaiEmbeddingModel: process.env.OPENAI_EMBEDDING_MODEL || "text-embedding-3-small",

    weatherProvider: (process.env.WEATHER_PROVIDER || "mock").toLowerCase(),
    openWeatherApiKey: process.env.OPENWEATHER_API_KEY || "",

    translationProvider: process.env.TRANSLATION_PROVIDER || "mock",
    vectorProvider: (process.env.VECTOR_PROVIDER || "local").toLowerCase(),
    memoryProvider: (process.env.MEMORY_PROVIDER || "json").toLowerCase(),
    memoryFile: env("TERRIS_MEMORY_FILE", "VELIA_MEMORY_FILE", process.env.MEMORY_FILE || "./src/storage/memory.json"),
    vectorIndexFile: env("TERRIS_VECTOR_INDEX_FILE", "VELIA_VECTOR_INDEX_FILE", process.env.VECTOR_INDEX_FILE || "./src/storage/vector-index.json"),
    weatherCacheFile: env("TERRIS_WEATHER_CACHE_FILE", "VELIA_WEATHER_CACHE_FILE", process.env.WEATHER_CACHE_FILE || "./src/storage/weather-cache.json"),

    terrisWaterEnabled: env("TERRIS_WATER_ENABLED", "VELIA_WATER_ENABLED", "true") === "true",
    terrisNutrientsEnabled: env("TERRIS_NUTRIENTS_ENABLED", "VELIA_NUTRIENTS_ENABLED", "true") === "true",
    terrisEnergyEnabled: env("TERRIS_ENERGY_ENABLED", "VELIA_ENERGY_ENABLED", "true") === "true",
    terrisOpsEnabled: env("TERRIS_OPS_ENABLED", "VELIA_OPS_ENABLED", "true") === "true",
    terrisProofEnabled: env("TERRIS_PROOF_ENABLED", "VELIA_PROOF_ENABLED", "true") === "true",
    terrisProtectEnabled: env("TERRIS_PROTECT_ENABLED", "VELIA_PROTECT_ENABLED", "false") === "true",
    terrisRiskApiEnabled: env("TERRIS_RISK_API_ENABLED", "VELIA_RISK_API_ENABLED", "false") === "true",

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
