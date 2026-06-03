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
import { scenarios, runFixtureEvaluation } from "../ai/evaluationHarness.js";
import { fetchJsonWithRetry } from "../services/httpClient.js";
import { scoreEvidence } from "../ai/confidenceEngine.js";
import { calculateDeterministicSignals, buildNormalizedFieldContext } from "../ai/deterministicIrrigation.js";
import { safetyGuardrails, containsUnsupportedClaim } from "../ai/safetyGuardrails.js";
import { getConfig } from "../config.js";

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

test("evaluation harness includes at least 35 executable fixtures", () => {
  assert.ok(scenarios.length >= 35);
  assert.ok(scenarios.some((s) => s.id === "invalid-llm-json"));
  assert.ok(scenarios.some((s) => s.id === "rag-retrieval-unavailable"));
  assert.ok(scenarios.every((s) => Array.isArray(s.expectedAllowedActions)));
  assert.ok(scenarios.every((s) => Array.isArray(s.forbiddenActions)));
  assert.ok(scenarios.every((s) => Array.isArray(s.confidenceRange) && s.confidenceRange.length === 2));
  assert.ok(scenarios.every((s) => Array.isArray(s.expectedMissingEvidence)));
  assert.ok(scenarios.every((s) => Array.isArray(s.forbiddenClaims)));
  assert.ok(scenarios.every((s) => "input" in s));
});

test("all evaluation fixtures pass deterministic engine", () => {
  const results = runFixtureEvaluation();
  const failed = results.filter((r) => !r.passed);
  if (failed.length > 0) {
    for (const r of failed) {
      const checks = Object.entries(r.checks).filter(([, v]) => !v).map(([k]) => k);
      console.error(`  FIXTURE FAIL: ${r.id} — ${checks.join(", ")}`);
    }
  }
  assert.equal(failed.length, 0, `${failed.length} evaluation fixtures failed`);
});

test("confidence engine: low irrigation need with high evidence produces high confidence", () => {
  const ctx = {
    crop: "tomato",
    soilType: "loam",
    irrigationMethod: "Drip",
    lastIrrigationAt: new Date(Date.now() - 2 * 86400000).toISOString(),
    recentObservation: "Looks normal",
    sensorData: { soilMoisturePercent: 32 },
    controllerStatus: "connected",
    coordinates: { lat: 36.7, lon: -119.4 },
    weather: { temperature: 22, rainChance: 10, weatherTimestamp: new Date().toISOString(), stale: false },
  };
  const result = scoreEvidence(ctx);
  assert.ok(result.confidenceScore >= 0.5, `expected >=0.5 got ${result.confidenceScore}`);
  assert.ok(result.evidenceChecked.includes("soil moisture sensor"));
  assert.ok(result.evidenceChecked.includes("recent irrigation log"));
  assert.ok(result.missingEvidence.length < 4);
});

test("confidence engine: high irrigation need with low evidence produces low confidence", () => {
  const ctx = {
    crop: null,
    soilType: null,
    irrigationMethod: null,
    lastIrrigationAt: null,
    recentObservation: null,
    weather: { stale: true },
  };
  const result = scoreEvidence(ctx);
  assert.ok(result.confidenceScore < 0.5, `expected <0.5 got ${result.confidenceScore}`);
  assert.equal(result.confidenceLabel, "low");
  assert.ok(result.missingEvidence.includes("crop type"));
  assert.ok(result.missingEvidence.includes("soil type"));
  assert.ok(result.missingEvidence.includes("weather freshness"));
});

test("confidence engine: high irrigation need with high evidence produces high confidence", () => {
  const ctx = {
    crop: "grape",
    soilType: "loam",
    irrigationMethod: "Drip",
    lastIrrigationAt: new Date(Date.now() - 6 * 86400000).toISOString(),
    recentObservation: "Leaves wilting, looks dry",
    sensorData: { soilMoisturePercent: 14 },
    controllerStatus: "connected",
    coordinates: { lat: 38.5, lon: -122.5 },
    weather: { temperature: 36, rainChance: 5, heatRisk: "high", weatherTimestamp: new Date().toISOString(), stale: false },
  };
  const result = scoreEvidence(ctx);
  assert.ok(result.confidenceScore >= 0.55, `expected >=0.55 got ${result.confidenceScore}`);
  assert.ok(result.evidenceChecked.includes("soil moisture sensor"));
  assert.ok(result.evidenceChecked.includes("recent field observation"));
});

test("confidence engine: conflicting signals reduce confidence", () => {
  const ctx = {
    crop: "tomato",
    soilType: "loam",
    irrigationMethod: "Drip",
    recentObservation: "Looks dry and stressed",
    weather: { rainChance: 75, rainfallForecastMm: 12, weatherTimestamp: new Date().toISOString(), stale: false },
  };
  const result = scoreEvidence(ctx);
  assert.ok(result.conflictingEvidence.length > 0, "expected conflicting evidence noted");
  assert.ok(result.conflictingEvidence.some((c) => /dry.*rain|rain.*dry/i.test(c)));
});

test("confidence engine: stale weather reduces confidence", () => {
  const ctxFresh = { crop: "tomato", soilType: "loam", irrigationMethod: "Drip", weather: { weatherTimestamp: new Date().toISOString(), stale: false } };
  const ctxStale = { crop: "tomato", soilType: "loam", irrigationMethod: "Drip", weather: { stale: true } };
  const fresh = scoreEvidence(ctxFresh);
  const stale = scoreEvidence(ctxStale);
  assert.ok(stale.confidenceScore < fresh.confidenceScore, `stale ${stale.confidenceScore} should be < fresh ${fresh.confidenceScore}`);
  assert.ok(stale.missingEvidence.includes("weather freshness"));
});

test("confidence engine: sensors increase confidence without overriding safety", () => {
  const withSensor = scoreEvidence({
    crop: "tomato", soilType: "loam", irrigationMethod: "Drip",
    sensorData: { soilMoisturePercent: 14 },
    weather: { weatherTimestamp: new Date().toISOString(), stale: false },
  });
  const withoutSensor = scoreEvidence({
    crop: "tomato", soilType: "loam", irrigationMethod: "Drip",
    weather: { weatherTimestamp: new Date().toISOString(), stale: false },
  });
  assert.ok(withSensor.confidenceScore > withoutSensor.confidenceScore);
  assert.ok(withSensor.evidenceChecked.includes("soil moisture sensor"));
});

test("deterministic safety: LLM cannot escalate to irrigate when threshold not met", () => {
  const baseCtx = buildNormalizedFieldContext({ field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "moderate", lastIrrigationAt: new Date(Date.now() - 2 * 86400000).toISOString() }, weather: { rainChance: 10, heatRisk: "low", forecastSummary: "Clear", weatherTimestamp: new Date().toISOString(), stale: false }, logs: [], observations: [] });
  const signals = calculateDeterministicSignals(baseCtx);
  assert.notEqual(signals.action, "irrigate", "moderate stress 2 days ago should not reach irrigate threshold");
  const decision = { action: "irrigate", confidenceScore: 0.7, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: baseCtx.weather, deterministicSignals: signals });
  assert.notEqual(enforced.action, "irrigate", "guardrails must block model escalation to irrigate");
  assert.ok(enforced.guardrailsTriggered.some((t) => t.includes("deterministic") || t.includes("blocked")));
});

test("deterministic safety: boundary values near irrigate threshold", () => {
  const cases = [
    { waterStressLevel: "high", heatRisk: "high", obs: "Looks dry", expectIrrigate: true },
    { waterStressLevel: "moderate", heatRisk: "low", obs: "Looks normal", expectIrrigate: false },
    { waterStressLevel: "low", heatRisk: "low", obs: "", expectIrrigate: false },
  ];
  for (const tc of cases) {
    const ctx = buildNormalizedFieldContext({ field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: tc.waterStressLevel, lastIrrigationAt: new Date(Date.now() - 5 * 86400000).toISOString() }, weather: { heatRisk: tc.heatRisk, rainChance: 5, forecastSummary: "Clear", weatherTimestamp: new Date().toISOString(), stale: false }, logs: [], observations: tc.obs ? [{ condition: tc.obs }] : [] });
    const signals = calculateDeterministicSignals(ctx);
    const irrigateDecided = signals.action === "irrigate";
    assert.equal(irrigateDecided, tc.expectIrrigate, `${tc.waterStressLevel}/${tc.heatRisk}: expected irrigate=${tc.expectIrrigate} got action=${signals.action} (needScore=${signals.needScore.toFixed(3)})`);
  }
});

test("deterministic safety: recent irrigation blocks irrigate", () => {
  const ctx = buildNormalizedFieldContext({ field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "high", lastIrrigationAt: new Date(Date.now() - 3 * 3600000).toISOString() }, weather: { heatRisk: "high", rainChance: 5, weatherTimestamp: new Date().toISOString(), stale: false }, logs: [], observations: [] });
  const signals = calculateDeterministicSignals(ctx);
  assert.ok(signals.rulesTriggered.includes("recent_irrigation"), "should trigger recent_irrigation rule");
  assert.ok(signals.needScore < 0.72, `recent irrigation should lower needScore (got ${signals.needScore.toFixed(3)})`);
  const decision = { action: "irrigate", confidenceScore: 0.8, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: {}, deterministicSignals: signals });
  assert.notEqual(enforced.action, "irrigate");
});

test("deterministic safety: wet observation blocks irrigate", () => {
  const ctx = buildNormalizedFieldContext({ field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "high" }, weather: { heatRisk: "low", rainChance: 5, weatherTimestamp: new Date().toISOString(), stale: false }, logs: [], observations: [{ condition: "Too wet — standing water visible" }] });
  const signals = calculateDeterministicSignals(ctx);
  assert.ok(signals.rulesTriggered.includes("wet_observation"));
  const decision = { action: "irrigate", confidenceScore: 0.8, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: {}, deterministicSignals: signals });
  assert.notEqual(enforced.action, "irrigate");
  assert.ok(enforced.guardrailsTriggered.includes("deterministic_wet_observation_overrode_irrigate"));
});

test("deterministic safety: frost risk blocks irrigate", () => {
  const ctx = buildNormalizedFieldContext({ field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "high" }, weather: { frostRisk: "high", rainChance: 5, weatherTimestamp: new Date().toISOString(), stale: false }, logs: [], observations: [] });
  const signals = calculateDeterministicSignals(ctx);
  assert.ok(signals.rulesTriggered.includes("frost_risk"));
  const decision = { action: "irrigate", confidenceScore: 0.8, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: ctx.weather, deterministicSignals: signals });
  assert.notEqual(enforced.action, "irrigate");
  assert.ok(enforced.guardrailsTriggered.includes("frost_risk_blocks_generic_irrigation"));
});

test("deterministic safety: meaningful rain forecast blocks irrigate", () => {
  const ctx = buildNormalizedFieldContext({ field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "high" }, weather: { rainChance: 70, rainfallForecastMm: 12, weatherTimestamp: new Date().toISOString(), stale: false }, logs: [], observations: [] });
  const signals = calculateDeterministicSignals(ctx);
  assert.ok(signals.rulesTriggered.includes("rain_likely"));
  const decision = { action: "irrigate", confidenceScore: 0.8, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: ctx.weather, deterministicSignals: signals });
  assert.notEqual(enforced.action, "irrigate");
});

test("deterministic safety: stale weather adds stale-weather field check", () => {
  const signals = { rulesTriggered: ["stale_weather"], needScore: 0.5, action: "check field first", urgency: "medium", missingData: [] };
  const decision = { action: "check field first", confidenceScore: 0.4, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: true }, deterministicSignals: signals });
  assert.ok(enforced.fieldChecks.some((c) => /stale/i.test(c)));
  assert.ok(enforced.guardrailWarnings.some((w) => /stale/i.test(w)));
});

test("guardrails: blocks unsupported exact soil moisture claim", () => {
  assert.ok(containsUnsupportedClaim("exact soil moisture is 32%"));
  assert.ok(!containsUnsupportedClaim("estimated soil moisture appears moderate"));
});

test("guardrails: blocks unsupported satellite claim", () => {
  assert.ok(containsUnsupportedClaim("satellite shows crop stress in the north block"));
  assert.ok(!containsUnsupportedClaim("Satellite evidence is not available for this recommendation"));
});

test("guardrails: blocks exact ET value claim", () => {
  assert.ok(containsUnsupportedClaim("ET is 4.5 mm today"));
  assert.ok(!containsUnsupportedClaim("ET source is not connected yet"));
});

test("guardrails: blocks exact duration and volume claims", () => {
  assert.ok(containsUnsupportedClaim("irrigate for exactly 90 minutes"));
  assert.ok(containsUnsupportedClaim("apply exactly 25 liters"));
  assert.ok(!containsUnsupportedClaim("Add flow rate to calculate a duration"));
});

test("guardrails: blocks guaranteed outcome language", () => {
  assert.ok(containsUnsupportedClaim("guaranteed yield improvement with this plan"));
  assert.ok(containsUnsupportedClaim("water savings of 30%"));
  assert.ok(!containsUnsupportedClaim("potential water savings (not yet verified)"));
});

test("environment-backed config loading works from env variables", () => {
  const saved = { PORT: process.env.PORT, LOG_LEVEL: process.env.LOG_LEVEL };
  process.env.PORT = "9999";
  process.env.LOG_LEVEL = "debug";
  const cfg = getConfig();
  assert.equal(cfg.port, 9999);
  assert.equal(cfg.logLevel, "debug");
  process.env.PORT = saved.PORT || "";
  process.env.LOG_LEVEL = saved.LOG_LEVEL || "";
  delete process.env.PORT;
  delete process.env.LOG_LEVEL;
});
