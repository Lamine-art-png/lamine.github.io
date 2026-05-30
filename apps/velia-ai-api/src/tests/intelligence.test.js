import test from "node:test";
import assert from "node:assert/strict";
import fs from "fs";
import os from "os";
import path from "path";
import { modelRouter } from "../ai/modelRouter.js";
import { parseDecisionJson, validateDecisionResponse } from "../ai/decisionSchema.js";
import { cosineSimilarity, LocalVectorStoreProvider } from "../providers/LocalVectorStoreProvider.js";
import { ragEngine } from "../ai/ragEngine.js";
import { normalizeOpenWeather, OpenWeatherProvider } from "../providers/OpenWeatherProvider.js";
import { irrigationDecisionAgent } from "../ai/irrigationDecisionAgent.js";
import { aiOrchestrator } from "../ai/aiOrchestrator.js";
import { detectRecurringPatterns, memoryStore } from "../ai/memoryStore.js";
import { scenarios } from "../ai/evaluationHarness.js";
import { fetchJsonWithRetry } from "../services/httpClient.js";

const sampleField = {
  id: "test-field",
  name: "North Block",
  crop: "tomato",
  soilType: "loam",
  irrigationMethod: "Drip",
  waterStressLevel: "moderate",
  lastIrrigationAt: new Date(Date.now() - 96 * 3600000).toISOString(),
};

const sampleWeather = {
  forecastSummary: "Hot and dry",
  rainChance: 8,
  rainfallForecastMm: 0,
  heatRisk: "elevated",
  frostRisk: "low",
  weatherTimestamp: new Date().toISOString(),
  source: "test",
  weatherSource: "test",
  stale: false,
};

test("real provider adapter selection and missing-key fallback", () => {
  process.env.LLM_PROVIDER = "openai";
  process.env.OPENAI_API_KEY = "test-openai-key";
  process.env.OPENAI_MODEL = "gpt-test";
  let provider = modelRouter.llmProvider();
  assert.equal(provider.name, "openai");
  assert.equal(provider.mode, "live");
  assert.equal(provider.model, "gpt-test");

  delete process.env.OPENAI_API_KEY;
  provider = modelRouter.llmProvider();
  assert.equal(provider.name, "mock");
  assert.equal(provider.mode, "mock");

  process.env.EMBEDDING_PROVIDER = "gemini";
  process.env.GEMINI_API_KEY = "test";
  process.env.GEMINI_EMBEDDING_MODEL = "text-embedding-test";
  const embeddingProvider = modelRouter.embeddingProvider();
  assert.equal(embeddingProvider.name, "gemini");
  assert.equal(embeddingProvider.mode, "live");

  delete process.env.LLM_PROVIDER;
  delete process.env.OPENAI_MODEL;
  delete process.env.EMBEDDING_PROVIDER;
  delete process.env.GEMINI_API_KEY;
  delete process.env.GEMINI_EMBEDDING_MODEL;
});

test("structured decision response validation", () => {
  const parsed = parseDecisionJson(JSON.stringify({
    action: "monitor",
    timing: "Today",
    urgency: "low",
    estimatedDurationRange: "0-30 min",
    reasons: ["rain likely"],
    uncertainties: [],
    missingData: [],
    fieldChecks: ["check topsoil"],
    risks: [],
    nextBestAction: "log observation",
    safetyNotes: ["validate in field"],
    verificationPlan: ["capture observation"],
  }));
  assert.equal(validateDecisionResponse(parsed).ok, true);
  assert.equal(validateDecisionResponse({ action: "invent" }).ok, false);
});

test("cosine similarity retrieval returns relevant metadata", async () => {
  const store = new LocalVectorStoreProvider({ rows: [] });
  await store.upsert({ id: "a", vector: [1, 0], text: "dry heat irrigation", source: { title: "A" } });
  await store.upsert({ id: "b", vector: [0, 1], text: "rain wait", source: { title: "B" } });
  const hits = await store.search([0.9, 0.1], 1);
  assert.equal(hits[0].id, "a");
  assert.equal(cosineSimilarity([1, 0], [1, 0]), 1);
  assert.equal(hits[0].source.title, "A");
});

test("RAG ingestion retrieves scored knowledge sources", async () => {
  const result = await ragEngine.retrieve("rain forecast irrigation wait", { topK: 3 });
  assert.equal(result.fallbackUsed, false);
  assert.ok(result.chunks.length > 0);
  assert.ok(result.chunks[0].relevanceScore >= result.chunks[result.chunks.length - 1].relevanceScore);
  assert.ok(result.sources[0].title);
});

test("OpenWeather normalization and stale cache fallback", async () => {
  const normalized = normalizeOpenWeather({
    current: { dt: Math.floor(Date.now() / 1000), name: "Farm", main: { temp: 36, humidity: 30 }, wind: { speed: 4 }, weather: [{ description: "clear sky" }], rain: { "1h": 0 } },
    forecast: { list: [{ dt: Math.floor(Date.now() / 1000) + 3600, pop: 0.7, rain: { "3h": 4 } }] },
    location: "Farm",
    lat: 10,
    lon: 20,
    ttlMinutes: 45,
  });
  assert.equal(normalized.weatherSource, "openweather");
  assert.equal(normalized.heatRisk, "high");
  assert.equal(normalized.rainChance, 70);
  assert.equal(normalized.etLabel, "not provided by OpenWeather");

  const cacheFile = path.join(os.tmpdir(), `velia-weather-${Date.now()}.json`);
  fs.writeFileSync(cacheFile, JSON.stringify({
    "10.0000,20.0000": { ...normalized, weatherTimestamp: new Date(Date.now() - 2 * 3600000).toISOString() },
  }));
  const provider = new OpenWeatherProvider({ apiKey: "key", cacheFile, fetchImpl: async () => { throw new Error("offline"); } });
  const stale = await provider.getContext({ lat: 10, lon: 20, location: "Farm" });
  assert.equal(stale.cached, true);
  assert.equal(stale.stale, true);
  assert.equal(stale.fallbackStatus, "openweather_unavailable_stale_cache");
});

test("provider retry handles transient timeout-style failures", async () => {
  let calls = 0;
  const result = await fetchJsonWithRetry("https://provider.test", {
    retries: 1,
    retryDelayMs: 1,
    fetchImpl: async () => {
      calls += 1;
      if (calls === 1) return { ok: false, status: 503, text: async () => JSON.stringify({ error: "temporary" }) };
      return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true }) };
    },
  });
  assert.equal(result.ok, true);
  assert.equal(calls, 2);
});

test("malformed model JSON falls back to deterministic decision with provenance", async () => {
  process.env.LLM_PROVIDER = "openai";
  process.env.OPENAI_API_KEY = "test-openai-key";
  const originalFetch = global.fetch;
  global.fetch = async () => ({ ok: true, status: 200, text: async () => JSON.stringify({ output_text: "not json" }) });
  try {
    const decision = await irrigationDecisionAgent.decide({
      field: sampleField,
      weather: sampleWeather,
      observations: [{ condition: "Looks dry" }],
      logs: [],
    });
    assert.equal(decision.provenance.fallbackStatus.llmFallbackUsed, true);
    assert.equal(decision.provenance.fallbackStatus.repairAttempted, true);
    assert.ok(decision.provenance.decisionTimestamp);
    assert.ok(decision.action);
    assert.ok(!JSON.stringify(decision).toLowerCase().includes("exact soil moisture"));
  } finally {
    global.fetch = originalFetch;
    delete process.env.LLM_PROVIDER;
    delete process.env.OPENAI_API_KEY;
  }
});

test("hybrid decision output, assistant grounding, offline fallback, and recurring memory patterns", async () => {
  const decision = await irrigationDecisionAgent.decide({
    field: { ...sampleField, id: "pattern-field" },
    weather: { ...sampleWeather, stale: true },
    observations: [{ condition: "Looks dry" }],
    logs: [],
  });
  assert.ok(decision.provenance);
  assert.ok(decision.provenance.weatherStale);
  assert.ok(decision.guardrailWarnings.length > 0);

  memoryStore.updateFieldMemory("pattern-field", { type: "observation", payload: { condition: "Looks dry" } });
  memoryStore.updateFieldMemory("pattern-field", { type: "observation", payload: { condition: "Leaves look stressed" } });
  const patterns = memoryStore.summarizeFieldMemory("pattern-field").recurringPatterns;
  assert.ok(patterns.some((p) => p.type === "repeated_dryness"));

  const assistant = await aiOrchestrator.run("assistant query", { query: "What are you missing?", fieldId: "pattern-field", decision });
  assert.equal(assistant.type, "assistant");
  assert.ok(/missing/i.test(assistant.answer));
  assert.ok(Array.isArray(assistant.sources));

  const directPatterns = detectRecurringPatterns({ observations: [{ condition: "Looks dry" }, { condition: "Looks dry" }], verificationOutcomes: [], recommendationHistory: [], providerProvenance: [], userOverrides: [] });
  assert.ok(directPatterns.some((p) => p.type === "repeated_dryness"));
});

test("evaluation harness includes at least 30 real scenarios", () => {
  assert.ok(scenarios.length >= 30);
  assert.ok(scenarios.some((s) => s.id === "invalid-llm-json"));
  assert.ok(scenarios.some((s) => s.id === "rag-retrieval-unavailable"));
});
