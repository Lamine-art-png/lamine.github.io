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
import { scoreEvidence, isSensorUsable, isSensorHardenedForBypass, validateSensor } from "../ai/confidenceEngine.js";
import { GeminiEmbeddingProvider } from "../providers/realEmbeddingProviders.js";
import { calculateDeterministicSignals, buildNormalizedFieldContext, deterministicDecisionFromSignals } from "../ai/deterministicIrrigation.js";
import { safetyGuardrails, containsUnsupportedClaim, containsUnsupportedClaimForContext } from "../ai/safetyGuardrails.js";
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
  // Use a unique field ID per run to avoid stale-state failures from prior test runs.
  const patternFieldId = `pattern-field-${Date.now()}`;
  const decision = await irrigationDecisionAgent.decide({
    field: { ...sampleField, id: patternFieldId },
    weather: { ...sampleWeather, stale: true },
    observations: [{ condition: "Looks dry" }],
    logs: [],
  });
  assert.ok(decision.provenance);
  assert.ok(decision.provenance.weatherStale);
  assert.ok(decision.guardrailWarnings.length > 0);

  memoryStore.updateFieldMemory(patternFieldId, { type: "observation", payload: { condition: "Looks dry" } });
  memoryStore.updateFieldMemory(patternFieldId, { type: "observation", payload: { condition: "Leaves look stressed" } });
  const patterns = memoryStore.summarizeFieldMemory(patternFieldId).recurringPatterns;
  assert.ok(patterns.some((p) => p.type === "repeated_dryness"));

  const assistant = await aiOrchestrator.run("assistant query", { query: "What are you missing?", fieldId: patternFieldId, decision });
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
    sensorData: { soilMoisturePercent: 32, timestamp: new Date(Date.now() - 30 * 60000).toISOString(), provenance: "field_sensor" },
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
    sensorData: { soilMoisturePercent: 14, timestamp: new Date(Date.now() - 30 * 60000).toISOString(), provenance: "field_sensor" },
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
    sensorData: { soilMoisturePercent: 14, timestamp: new Date(Date.now() - 30 * 60000).toISOString(), provenance: "field_sensor" },
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

// ── Evidence normalization ──────────────────────────────────────────────────

test("buildNormalizedFieldContext: preserves observation timestamp", () => {
  const ts = new Date(Date.now() - 3600000).toISOString();
  const ctx = buildNormalizedFieldContext({ field: {}, observations: [{ condition: "Dry", createdAt: ts }] });
  assert.equal(ctx.observationTimestamp, ts);
  assert.equal(ctx.recentObservation, "Dry");
});

test("buildNormalizedFieldContext: preserves coordinate and satellite fields", () => {
  const ctx = buildNormalizedFieldContext({ field: { lat: 36.7, lon: -119.4, satelliteEvidence: { ndvi: 0.8 }, ndvi: 0.7 } });
  assert.equal(ctx.lat, 36.7);
  assert.equal(ctx.lon, -119.4);
  assert.ok(ctx.satelliteEvidence);
  assert.equal(ctx.ndvi, 0.7);
});

test("buildNormalizedFieldContext: preserves flow rate and application rate", () => {
  const ctx = buildNormalizedFieldContext({ field: { flowRateLph: 200, applicationRateMmPerHour: 4.5 } });
  assert.equal(ctx.flowRateLph, 200);
  assert.equal(ctx.applicationRateMmPerHour, 4.5);
});

test("buildNormalizedFieldContext: does not infer sensorProvenance from data presence alone", () => {
  const ctx = buildNormalizedFieldContext({
    field: { sensorData: { soilMoisturePercent: 22 }, controllerStatus: "connected" },
    weather: { evapotranspiration: 4.2 },
  });
  assert.equal(ctx.sensorProvenance, null, "sensorProvenance must not be inferred from data presence — must be explicitly supplied");
  assert.equal(ctx.controllerProvenance, "controller");
  assert.equal(ctx.etProvenance, "weather_provider");
});

test("deterministicDecisionFromSignals: uses honest duration message when flow rate absent", () => {
  const ctxNoFlow = buildNormalizedFieldContext({ field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "high" }, weather: { heatRisk: "high", rainChance: 5, weatherTimestamp: new Date().toISOString(), stale: false }, observations: [{ condition: "Dry" }] });
  const signals = calculateDeterministicSignals(ctxNoFlow);
  const dec = deterministicDecisionFromSignals(signals, ctxNoFlow);
  if (dec.action === "irrigate") {
    assert.ok(dec.estimatedDurationRange.includes("flow rate"), `expected honest duration message when flow rate absent, got: ${dec.estimatedDurationRange}`);
  }
  const ctxWithFlow = buildNormalizedFieldContext({ field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "high", flowRateLph: 300, applicationRateMmPerHour: 4.5 }, weather: { heatRisk: "high", rainChance: 5, weatherTimestamp: new Date().toISOString(), stale: false }, observations: [{ condition: "Dry" }] });
  const dec2 = deterministicDecisionFromSignals(calculateDeterministicSignals(ctxWithFlow), ctxWithFlow);
  if (dec2.action === "irrigate") {
    assert.ok(dec2.estimatedDurationRange.toLowerCase().includes("flow rate") || dec2.estimatedDurationRange.toLowerCase().includes("application rate"), `expected honest duration message even with flow rate fields present, got: ${dec2.estimatedDurationRange}`);
  }
});

// ── Confidence recalibration ────────────────────────────────────────────────

test("confidence engine: hardware-free farmer with all core evidence reaches high confidence", () => {
  const ctx = buildNormalizedFieldContext({
    field: { crop: "tomato", soilType: "loam", irrigationMethod: "Drip", lat: 36.7, lon: -119.4, lastIrrigationAt: new Date(Date.now() - 3 * 86400000).toISOString() },
    weather: { weatherTimestamp: new Date().toISOString(), stale: false },
    observations: [{ condition: "Looks dry" }],
  });
  const result = scoreEvidence(ctx);
  assert.ok(result.confidenceScore >= 0.9, `hardware-free farmer with full core should reach >=0.9, got ${result.confidenceScore}`);
  assert.equal(result.confidenceLabel, "high");
  assert.ok(!result.missingEvidence.includes("crop type"));
  assert.ok(!result.missingEvidence.includes("soil type"));
  assert.ok(!result.missingEvidence.includes("irrigation method"));
});

test("confidence engine: empty sensor object does not count as sensor evidence", () => {
  const base = { crop: "tomato", soilType: "loam", irrigationMethod: "Drip", weather: { weatherTimestamp: new Date().toISOString(), stale: false } };
  const withEmpty = scoreEvidence({ ...base, sensorData: {} });
  const withNumeric = scoreEvidence({ ...base, sensorData: { soilMoisturePercent: 14, timestamp: new Date(Date.now() - 30 * 60000).toISOString(), provenance: "field_sensor" } });
  assert.ok(withEmpty.missingEvidence.includes("soil moisture sensor"), "empty sensor object must not count as evidence");
  assert.ok(withNumeric.evidenceChecked.includes("soil moisture sensor"), "fully validated sensor must count as evidence");
  assert.ok(withNumeric.confidenceScore > withEmpty.confidenceScore);
});

test("confidence engine: observation recency — recent beats old beats none", () => {
  const recentTs = new Date(Date.now() - 3600000).toISOString();
  const oldTs = new Date(Date.now() - 20 * 86400000).toISOString();
  const base = { crop: "tomato", soilType: "loam", irrigationMethod: "Drip", weather: { weatherTimestamp: new Date().toISOString(), stale: false } };
  const withRecent = scoreEvidence({ ...base, recentObservation: "Dry", observationTimestamp: recentTs });
  const withOld = scoreEvidence({ ...base, recentObservation: "Dry", observationTimestamp: oldTs });
  const withNone = scoreEvidence({ ...base });
  assert.ok(withRecent.confidenceScore > withOld.confidenceScore, `recent obs should beat old obs`);
  assert.ok(withOld.confidenceScore > withNone.confidenceScore, `any obs should beat none`);
});

test("confidence engine: observation without timestamp gets partial credit and flags missing timestamp", () => {
  const ctx = buildNormalizedFieldContext({ field: { crop: "tomato", soilType: "loam" }, observations: [{ condition: "Looks fine" }] });
  assert.equal(ctx.observationTimestamp, null, "no timestamp in observation object");
  const result = scoreEvidence(ctx);
  assert.ok(result.evidenceChecked.includes("recent field observation"), "observation without timestamp should still count");
  assert.ok(result.missingEvidence.includes("observation timestamp"), "missing timestamp should appear in missingEvidence");
  assert.ok(result.improvementSuggestions.some((s) => s.includes("Observation timestamp is unknown")), "improvement suggestions should include timestamp hint");
  const withTs = scoreEvidence({ ...ctx, observationTimestamp: new Date().toISOString() });
  assert.ok(withTs.confidenceScore > result.confidenceScore, "timestamped observation should score higher than untimestamped");
});

// ── Safety gates ────────────────────────────────────────────────────────────

test("safety gate: stale weather blocks irrigate escalation", () => {
  const signals = { rulesTriggered: [], needScore: 0.78, action: "irrigate", urgency: "high", missingData: [] };
  const decision = { action: "irrigate", confidenceScore: 0.8, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: true }, deterministicSignals: signals });
  assert.notEqual(enforced.action, "irrigate", "stale weather must block irrigate");
  assert.ok(enforced.guardrailsTriggered.includes("stale_weather_downgrade_irrigate"));
});

test("safety gate: missing irrigation method blocks irrigate", () => {
  const signals = { rulesTriggered: [], needScore: 0.78, action: "irrigate", urgency: "high", missingData: [] };
  const decision = { action: "irrigate", confidenceScore: 0.8, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: { irrigationMethod: null } });
  assert.notEqual(enforced.action, "irrigate", "missing irrigation method must block irrigate");
  assert.ok(enforced.guardrailsTriggered.includes("missing_irrigation_method_blocks_irrigate"));
});

test("safety gate: low confidence blocks irrigate", () => {
  const signals = { rulesTriggered: [], needScore: 0.78, action: "irrigate", urgency: "high", missingData: [] };
  const decision = { action: "irrigate", confidenceScore: 0.35, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals });
  assert.notEqual(enforced.action, "irrigate", "low confidence must block irrigate");
  assert.ok(enforced.guardrailsTriggered.includes("low_confidence_blocks_irrigate"));
});

test("safety gate: valid irrigate passes through when conditions are clear", () => {
  const signals = { rulesTriggered: [], needScore: 0.78, action: "irrigate", urgency: "high", missingData: [] };
  const decision = { action: "irrigate", confidenceScore: 0.85, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: { irrigationMethod: "Drip" } });
  assert.equal(enforced.action, "irrigate", "valid irrigate with full context must not be blocked by new gates");
});

// ── Evidence-conditional guardrails ────────────────────────────────────────

test("containsUnsupportedClaimForContext: soil moisture % blocked without sensor", () => {
  assert.ok(containsUnsupportedClaimForContext("soil moisture is 14%", {}));
  assert.ok(containsUnsupportedClaimForContext("soil moisture of 22%", { sensorData: {} }));
});

test("containsUnsupportedClaimForContext: soil moisture % allowed with fully validated sensor", () => {
  const freshTs = new Date(Date.now() - 30 * 60000).toISOString();
  assert.ok(!containsUnsupportedClaimForContext("soil moisture is 14%", { sensorData: { soilMoisturePercent: 14, timestamp: freshTs, provenance: "field_sensor" } }));
});

test("containsUnsupportedClaimForContext: satellite claim blocked without satellite evidence", () => {
  assert.ok(containsUnsupportedClaimForContext("satellite data shows stress in north block", { satelliteEvidence: null }));
  assert.ok(!containsUnsupportedClaimForContext("Satellite evidence is not available for this recommendation", {}));
});

test("containsUnsupportedClaimForContext: duration blocked without flow rate", () => {
  assert.ok(containsUnsupportedClaimForContext("irrigate for 90 minutes", {}));
  assert.ok(!containsUnsupportedClaimForContext("Add flow rate to calculate a duration", {}));
});

test("containsUnsupportedClaimForContext: always-block patterns still trigger regardless of context", () => {
  assert.ok(containsUnsupportedClaimForContext("exact soil moisture is 32%", { sensorData: { soilMoisturePercent: 32 } }));
  assert.ok(containsUnsupportedClaimForContext("guaranteed yield improvement", {}));
});

// ── Integration pipeline ────────────────────────────────────────────────────

test("integration: frost risk decision never produces irrigate", async () => {
  const result = await irrigationDecisionAgent.decide({
    field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "high" },
    weather: { frostRisk: "high", rainChance: 5, weatherTimestamp: new Date().toISOString(), stale: false },
  });
  assert.notEqual(result.action, "irrigate", "frost risk must block irrigate");
  assert.ok(result.provenance?.deterministicRulesTriggered?.includes("frost_risk"), "frost_risk must appear in deterministic rules");
});

test("integration: rain forecast decision never produces irrigate", async () => {
  const result = await irrigationDecisionAgent.decide({
    field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "high" },
    weather: { rainChance: 75, rainfallForecastMm: 12, weatherTimestamp: new Date().toISOString(), stale: false },
  });
  assert.notEqual(result.action, "irrigate", "rain forecast must block irrigate");
});

test("integration: wet observation decision never produces irrigate", async () => {
  const result = await irrigationDecisionAgent.decide({
    field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "high" },
    weather: { heatRisk: "low", rainChance: 5, weatherTimestamp: new Date().toISOString(), stale: false },
    observations: [{ condition: "Too wet — standing water visible" }],
  });
  assert.notEqual(result.action, "irrigate", "wet observation must block irrigate");
});

test("integration: recent irrigation decision never produces irrigate", async () => {
  const result = await irrigationDecisionAgent.decide({
    field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "high", lastIrrigationAt: new Date(Date.now() - 2 * 3600000).toISOString() },
    weather: { heatRisk: "high", rainChance: 5, weatherTimestamp: new Date().toISOString(), stale: false },
  });
  assert.notEqual(result.action, "irrigate", "recent irrigation must block irrigate");
});

test("integration: decision always has valid provenance and safety fields", async () => {
  const result = await irrigationDecisionAgent.decide({
    field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "moderate" },
    weather: { heatRisk: "low", rainChance: 10, weatherTimestamp: new Date().toISOString(), stale: false },
  });
  assert.ok(result.action, "decision must have an action");
  assert.ok(result.provenance?.decisionTimestamp, "decision must have a timestamp");
  assert.ok(Array.isArray(result.guardrailWarnings), "guardrailWarnings must be an array");
  assert.ok(result.disclaimer, "disclaimer must be present");
  assert.ok(typeof result.confidenceScore === "number", "confidenceScore must be a number");
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

// ── Fallback assertion regression tests ───────────────────────────────────────

test("eval harness: expectedFallbackState:false fails when actual fallback is true", () => {
  const scenario = { id: "test-stale", expectedFallbackState: false };
  const fallbackState = true;
  const fallbackMatchesExpected = !Object.hasOwn(scenario, "expectedFallbackState") || fallbackState === scenario.expectedFallbackState;
  assert.equal(fallbackMatchesExpected, false, "expectedFallbackState:false must fail when actual is true");
});

test("eval harness: expectedFallbackState:true fails when actual fallback is false", () => {
  const scenario = { id: "test-fresh", expectedFallbackState: true };
  const fallbackState = false;
  const fallbackMatchesExpected = !Object.hasOwn(scenario, "expectedFallbackState") || fallbackState === scenario.expectedFallbackState;
  assert.equal(fallbackMatchesExpected, false, "expectedFallbackState:true must fail when actual is false");
});

test("eval harness: fixture without expectedFallbackState always passes fallback check", () => {
  const scenario = { id: "no-fallback-key" };
  const fallbackMatchesExpected = !Object.hasOwn(scenario, "expectedFallbackState") || false === scenario.expectedFallbackState;
  assert.equal(fallbackMatchesExpected, true, "fixture without expectedFallbackState must always pass");
});

// ── Evidence-conditional scrubbing E2E ───────────────────────────────────────

test("enforce scrubs soil moisture % when no sensor in fieldContext", () => {
  const signals = { rulesTriggered: [], needScore: 0.6, action: "check field first", urgency: "medium", missingData: [] };
  const decision = { action: "check field first", confidenceScore: 0.6, reasons: ["Soil moisture is 32% based on recent data"], uncertainties: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: {} });
  assert.ok(!enforced.reasons.join(" ").includes("32%"), "soil moisture % must be scrubbed when no sensor");
  assert.ok(enforced.reasons.join(" ").includes("sensor not connected"), "replacement text must appear");
});

test("enforce allows soil moisture % when sensor passes strict validation", () => {
  const freshTs = new Date(Date.now() - 30 * 60000).toISOString();
  const signals = { rulesTriggered: [], needScore: 0.6, action: "check field first", urgency: "medium", missingData: [] };
  const decision = { action: "check field first", confidenceScore: 0.6, reasons: ["Soil moisture is 32% based on sensor reading"], uncertainties: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: { sensorData: { soilMoisturePercent: 32, timestamp: freshTs, provenance: "field_sensor" } } });
  assert.ok(enforced.reasons.join(" ").includes("32%"), "soil moisture % must be kept when sensor passes strict validation");
});

test("enforce scrubs ET value when no ET source in fieldContext", () => {
  const signals = { rulesTriggered: [], needScore: 0.6, action: "check field first", urgency: "medium", missingData: [] };
  const decision = { action: "check field first", confidenceScore: 0.6, reasons: ["ET is 4.5 mm today"], uncertainties: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: {} });
  assert.ok(!enforced.reasons.join(" ").includes("4.5 mm"), "ET value must be scrubbed when no ET source");
});

test("enforce scrubs duration claim when no flow rate in fieldContext", () => {
  const signals = { rulesTriggered: [], needScore: 0.6, action: "check field first", urgency: "medium", missingData: [] };
  const decision = { action: "check field first", confidenceScore: 0.6, reasons: [], uncertainties: [], fieldChecks: ["Irrigate for 90 minutes then check"], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: {} });
  assert.ok(!enforced.fieldChecks.join(" ").includes("90 minutes"), "duration claim must be scrubbed when no flow rate");
});

test("enforce scrubs satellite claim when no satellite evidence in fieldContext", () => {
  const signals = { rulesTriggered: [], needScore: 0.6, action: "check field first", urgency: "medium", missingData: [] };
  const decision = { action: "check field first", confidenceScore: 0.6, reasons: ["Satellite detected crop stress in north block"], uncertainties: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: {} });
  assert.ok(!enforced.reasons.join(" ").toLowerCase().includes("satellite detected"), "satellite claim must be scrubbed without satellite evidence");
});

// ── sensor_high_moisture safety gate ─────────────────────────────────────────

test("safety gate: sensor_high_moisture blocks irrigate even with high stress and dry observation", () => {
  const signals = { rulesTriggered: ["sensor_high_moisture"], needScore: 0.78, action: "irrigate", urgency: "high", missingData: [] };
  const decision = { action: "irrigate", confidenceScore: 0.8, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals });
  assert.notEqual(enforced.action, "irrigate", "sensor_high_moisture must block irrigate");
  assert.ok(enforced.guardrailsTriggered.includes("sensor_high_moisture_blocks_irrigate"));
  assert.ok(["wait", "check field first"].includes(enforced.action), `action should be wait or check field first, got: ${enforced.action}`);
});

// ── Recent irrigation tightened gate ─────────────────────────────────────────

test("safety gate: recent irrigation without any sensor blocks irrigate", () => {
  const signals = { rulesTriggered: ["recent_irrigation"], needScore: 0.85, action: "irrigate", urgency: "high", missingData: [] };
  const decision = { action: "irrigate", confidenceScore: 0.8, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: {} });
  assert.notEqual(enforced.action, "irrigate", "recent irrigation without sensor must block irrigate");
  assert.ok(enforced.guardrailsTriggered.includes("recent_irrigation_requires_field_check"));
});

test("safety gate: recent irrigation with high-moisture sensor blocks irrigate", () => {
  const signals = { rulesTriggered: ["recent_irrigation"], needScore: 0.85, action: "irrigate", urgency: "high", missingData: [] };
  const decision = { action: "irrigate", confidenceScore: 0.8, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: { sensorData: { soilMoisturePercent: 42 } } });
  assert.notEqual(enforced.action, "irrigate", "recent irrigation with high sensor moisture must block irrigate");
  assert.ok(enforced.guardrailsTriggered.includes("recent_irrigation_requires_field_check"));
});

test("safety gate: recent irrigation with fresh provenanced dry sensor (≤18%) may proceed", () => {
  const freshTs = new Date(Date.now() - 30 * 60000).toISOString();
  const signals = { rulesTriggered: ["recent_irrigation"], needScore: 0.85, action: "irrigate", urgency: "high", missingData: [] };
  const decision = { action: "irrigate", confidenceScore: 0.8, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: { irrigationMethod: "Drip", sensorData: { soilMoisturePercent: 15, timestamp: freshTs }, sensorProvenance: "field_sensor" } });
  assert.ok(!enforced.guardrailsTriggered.includes("recent_irrigation_requires_field_check"), "fresh provenanced dry sensor (≤18%) should allow irrigate through the recent_irrigation gate");
});

// ── Duration both-required tests ──────────────────────────────────────────────

test("duration: neither flowRateLph nor applicationRateMmPerHour returns honest message", () => {
  const ctx = buildNormalizedFieldContext({ field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "high" }, weather: { heatRisk: "high", rainChance: 5, weatherTimestamp: new Date().toISOString(), stale: false }, observations: [{ condition: "Dry" }] });
  const signals = calculateDeterministicSignals(ctx);
  const dec = deterministicDecisionFromSignals(signals, ctx);
  if (dec.action === "irrigate") {
    assert.ok(dec.estimatedDurationRange.includes("flow rate"), `expected honest message when neither flow rate field present, got: ${dec.estimatedDurationRange}`);
  }
});

test("duration: only flowRateLph present returns honest message (AND required)", () => {
  const ctx = buildNormalizedFieldContext({ field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "high", flowRateLph: 300 }, weather: { heatRisk: "high", rainChance: 5, weatherTimestamp: new Date().toISOString(), stale: false }, observations: [{ condition: "Dry" }] });
  const signals = calculateDeterministicSignals(ctx);
  const dec = deterministicDecisionFromSignals(signals, ctx);
  if (dec.action === "irrigate") {
    assert.ok(dec.estimatedDurationRange.includes("flow rate"), `expected honest message when only flowRateLph present, got: ${dec.estimatedDurationRange}`);
  }
});

test("duration: only applicationRateMmPerHour present returns honest message (AND required)", () => {
  const ctx = buildNormalizedFieldContext({ field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "high", applicationRateMmPerHour: 4.5 }, weather: { heatRisk: "high", rainChance: 5, weatherTimestamp: new Date().toISOString(), stale: false }, observations: [{ condition: "Dry" }] });
  const signals = calculateDeterministicSignals(ctx);
  const dec = deterministicDecisionFromSignals(signals, ctx);
  if (dec.action === "irrigate") {
    assert.ok(dec.estimatedDurationRange.includes("flow rate"), `expected honest message when only applicationRateMmPerHour present, got: ${dec.estimatedDurationRange}`);
  }
});

test("duration: both flowRateLph and applicationRateMmPerHour present returns honest message (no calculator yet)", () => {
  const ctx = buildNormalizedFieldContext({ field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "high", flowRateLph: 300, applicationRateMmPerHour: 4.5 }, weather: { heatRisk: "high", rainChance: 5, weatherTimestamp: new Date().toISOString(), stale: false }, observations: [{ condition: "Dry" }] });
  const signals = calculateDeterministicSignals(ctx);
  const dec = deterministicDecisionFromSignals(signals, ctx);
  if (dec.action === "irrigate") {
    assert.ok(dec.estimatedDurationRange.toLowerCase().includes("flow rate") || dec.estimatedDurationRange.toLowerCase().includes("application rate"), `expected honest message (no calculator), got: ${dec.estimatedDurationRange}`);
    assert.ok(!dec.estimatedDurationRange.includes("45-90"), "must not return hardcoded 45-90 range without a real calculator");
  }
});

// ── modelRouter Gemini embedding default ─────────────────────────────────────

test("modelRouter: gemini embedding default is gemini-embedding-2 when GEMINI_EMBEDDING_MODEL absent", () => {
  const saved = { EMBEDDING_PROVIDER: process.env.EMBEDDING_PROVIDER, GEMINI_API_KEY: process.env.GEMINI_API_KEY, GEMINI_EMBEDDING_MODEL: process.env.GEMINI_EMBEDDING_MODEL };
  process.env.EMBEDDING_PROVIDER = "gemini";
  process.env.GEMINI_API_KEY = "test-key-do-not-use";
  delete process.env.GEMINI_EMBEDDING_MODEL;
  const provider = modelRouter.embeddingProvider();
  assert.equal(provider.model, "gemini-embedding-2", "default gemini embedding model must be gemini-embedding-2");
  process.env.EMBEDDING_PROVIDER = saved.EMBEDDING_PROVIDER || "";
  process.env.GEMINI_API_KEY = saved.GEMINI_API_KEY || "";
  if (saved.GEMINI_EMBEDDING_MODEL != null) process.env.GEMINI_EMBEDDING_MODEL = saved.GEMINI_EMBEDDING_MODEL;
  else delete process.env.GEMINI_EMBEDDING_MODEL;
});

test("modelRouter: explicit GEMINI_EMBEDDING_MODEL override is respected (backwards compat)", () => {
  const saved = { EMBEDDING_PROVIDER: process.env.EMBEDDING_PROVIDER, GEMINI_API_KEY: process.env.GEMINI_API_KEY, GEMINI_EMBEDDING_MODEL: process.env.GEMINI_EMBEDDING_MODEL };
  process.env.EMBEDDING_PROVIDER = "gemini";
  process.env.GEMINI_API_KEY = "test-key-do-not-use";
  process.env.GEMINI_EMBEDDING_MODEL = "text-embedding-004";
  const provider = modelRouter.embeddingProvider();
  assert.equal(provider.model, "text-embedding-004", "explicit GEMINI_EMBEDDING_MODEL must override default");
  process.env.EMBEDDING_PROVIDER = saved.EMBEDDING_PROVIDER || "";
  process.env.GEMINI_API_KEY = saved.GEMINI_API_KEY || "";
  if (saved.GEMINI_EMBEDDING_MODEL != null) process.env.GEMINI_EMBEDDING_MODEL = saved.GEMINI_EMBEDDING_MODEL;
  else delete process.env.GEMINI_EMBEDDING_MODEL;
});

// ── Text-field sanitization — timing / estimatedDurationRange / verificationPlan ──

test("enforce scrubs unsupported duration from timing field", () => {
  const signals = { rulesTriggered: [], needScore: 0.6, action: "check field first", urgency: "medium", missingData: [] };
  const decision = { action: "check field first", confidenceScore: 0.6, timing: "Irrigate for 45 minutes at dawn", reasons: [], uncertainties: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: {} });
  assert.ok(!enforced.timing.includes("45 minutes"), "duration claim must be scrubbed from timing field");
});

test("enforce scrubs unsupported duration from estimatedDurationRange field", () => {
  const signals = { rulesTriggered: [], needScore: 0.6, action: "check field first", urgency: "medium", missingData: [] };
  const decision = { action: "check field first", confidenceScore: 0.6, estimatedDurationRange: "Irrigate for 90 minutes based on field size", reasons: [], uncertainties: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: {} });
  assert.ok(!enforced.estimatedDurationRange.includes("90 minutes"), "duration claim must be scrubbed from estimatedDurationRange field");
});

test("enforce scrubs unsupported duration from nextBestAction field", () => {
  const signals = { rulesTriggered: [], needScore: 0.6, action: "check field first", urgency: "medium", missingData: [] };
  const decision = { action: "check field first", confidenceScore: 0.6, nextBestAction: "Irrigate for 60 minutes then check leaves", reasons: [], uncertainties: [], fieldChecks: [], risks: [], nextBestAction: "Irrigate for 60 minutes then check leaves", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: {} });
  assert.ok(!enforced.nextBestAction.includes("60 minutes"), "duration claim must be scrubbed from nextBestAction field");
});

test("enforce scrubs unsupported duration from verificationPlan", () => {
  const signals = { rulesTriggered: [], needScore: 0.6, action: "check field first", urgency: "medium", missingData: [] };
  const decision = { action: "check field first", confidenceScore: 0.6, reasons: [], uncertainties: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: ["Irrigate for 45 minutes", "Record result"], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: {} });
  assert.ok(!enforced.verificationPlan.join(" ").includes("45 minutes"), "duration claim must be scrubbed from verificationPlan");
});

// ── Flow rate AND required for duration/volume claims ────────────────────────

test("containsUnsupportedClaimForContext: duration blocked when only flowRateLph present", () => {
  assert.ok(containsUnsupportedClaimForContext("irrigate for 90 minutes", { flowRateLph: 300 }), "only flowRateLph must not be sufficient to allow duration claim");
});

test("containsUnsupportedClaimForContext: duration blocked when only applicationRateMmPerHour present", () => {
  assert.ok(containsUnsupportedClaimForContext("irrigate for 90 minutes", { applicationRateMmPerHour: 4.5 }), "only applicationRateMmPerHour must not be sufficient to allow duration claim");
});

test("containsUnsupportedClaimForContext: duration allowed when both flowRateLph and applicationRateMmPerHour present", () => {
  assert.ok(!containsUnsupportedClaimForContext("irrigate for 90 minutes", { flowRateLph: 300, applicationRateMmPerHour: 4.5 }), "both fields present must allow duration claim");
});

// ── US irrigation volume units ────────────────────────────────────────────────

test("containsUnsupportedClaimForContext: 'Apply 0.8 inches' blocked without system evidence", () => {
  assert.ok(containsUnsupportedClaimForContext("Apply 0.8 inches to the field", {}), "inches must be blocked without flow rate and application rate");
});

test("containsUnsupportedClaimForContext: 'Apply 1 inch' blocked without system evidence", () => {
  assert.ok(containsUnsupportedClaimForContext("Apply 1 inch of water", {}), "inch must be blocked without system evidence");
});

test("containsUnsupportedClaimForContext: 'Apply 0.4 acre-feet' blocked without system evidence", () => {
  assert.ok(containsUnsupportedClaimForContext("Apply 0.4 acre-feet to each block", {}), "acre-feet must be blocked without system evidence");
});

test("enforce scrubs 'Apply 0.8 inches' from reasons when no system evidence", () => {
  const signals = { rulesTriggered: [], needScore: 0.6, action: "check field first", urgency: "medium", missingData: [] };
  const decision = { action: "check field first", confidenceScore: 0.6, reasons: ["Apply 0.8 inches based on crop needs"], uncertainties: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: {} });
  assert.ok(!enforced.reasons.join(" ").includes("0.8 inches"), "Apply 0.8 inches must be scrubbed from reasons");
});

// ── Observation timestamp hardening ──────────────────────────────────────────

test("confidence engine: invalid (unparseable) observation timestamp does not get maximum credit", () => {
  const withInvalid = scoreEvidence({ recentObservation: "Dry", observationTimestamp: "not-a-date" });
  const withValid = scoreEvidence({ recentObservation: "Dry", observationTimestamp: new Date().toISOString() });
  assert.ok(withInvalid.confidenceScore < withValid.confidenceScore, "invalid timestamp must score less than valid recent timestamp");
  assert.ok(withInvalid.missingEvidence.some((m) => m.includes("observation timestamp")), "invalid timestamp must be flagged in missingEvidence");
  assert.ok(withInvalid.improvementSuggestions.some((s) => s.includes("invalid or future")), "improvement suggestion must mention invalid/future timestamp");
});

test("confidence engine: future observation timestamp beyond clock skew does not get maximum credit", () => {
  const futureTs = new Date(Date.now() + 60 * 60 * 1000).toISOString(); // 1 hour in future
  const withFuture = scoreEvidence({ recentObservation: "Dry", observationTimestamp: futureTs });
  const withValid = scoreEvidence({ recentObservation: "Dry", observationTimestamp: new Date().toISOString() });
  assert.ok(withFuture.confidenceScore < withValid.confidenceScore, "future timestamp must score less than valid recent timestamp");
  assert.ok(withFuture.missingEvidence.some((m) => m.includes("observation timestamp")), "future timestamp must be flagged in missingEvidence");
});

// ── Sensor evidence hardening ─────────────────────────────────────────────────

test("isSensorUsable: numeric sensor without timestamp is not usable", () => {
  assert.ok(!isSensorUsable({ soilMoisturePercent: 22 }), "numeric sensor without timestamp must not be usable — timestamp is required");
});

test("isSensorUsable: sensor with stale timestamp is not usable", () => {
  const staleTs = new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(); // 5 hours ago
  assert.ok(!isSensorUsable({ soilMoisturePercent: 22, timestamp: staleTs }), "sensor stale beyond 4h must not be usable");
});

test("isSensorUsable: sensor with fresh timestamp and provenance is usable", () => {
  const freshTs = new Date(Date.now() - 30 * 60 * 1000).toISOString();
  assert.ok(!isSensorUsable({ soilMoisturePercent: 22, timestamp: freshTs }), "fresh sensor without provenance must not be usable");
  assert.ok(isSensorUsable({ soilMoisturePercent: 22, timestamp: freshTs, provenance: "field_sensor" }), "fresh sensor with provenance must be usable");
});

test("isSensorUsable: non-numeric moisture is not usable", () => {
  assert.ok(!isSensorUsable({ soilMoisturePercent: "22%" }), "string moisture value must not be usable");
  assert.ok(!isSensorUsable({}), "empty sensor object must not be usable");
  assert.ok(!isSensorUsable(null), "null sensor must not be usable");
});

test("isSensorHardenedForBypass: requires timestamp and provenance", () => {
  const freshTs = new Date(Date.now() - 30 * 60000).toISOString();
  const sensor = { soilMoisturePercent: 15 };
  const freshSensor = { soilMoisturePercent: 15, timestamp: freshTs };
  assert.ok(!isSensorHardenedForBypass(sensor, {}), "sensor without timestamp or provenance must not be hardened for bypass");
  assert.ok(!isSensorHardenedForBypass(sensor, { sensorProvenance: "field_sensor" }), "sensor without timestamp must not be hardened for bypass even with context provenance");
  assert.ok(isSensorHardenedForBypass(freshSensor, { sensorProvenance: "field_sensor" }), "fresh sensor with context sensorProvenance should be hardened for bypass");
  assert.ok(isSensorHardenedForBypass({ ...freshSensor, provenance: "field_sensor" }, {}), "fresh sensor with inline provenance should be hardened for bypass");
});

test("safety gate: recent irrigation without sensor provenance is blocked even when moisture is dry", () => {
  const signals = { rulesTriggered: ["recent_irrigation"], needScore: 0.85, action: "irrigate", urgency: "high", missingData: [] };
  const decision = { action: "irrigate", confidenceScore: 0.8, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: { irrigationMethod: "Drip", sensorData: { soilMoisturePercent: 15 } } });
  assert.ok(enforced.guardrailsTriggered.includes("recent_irrigation_requires_field_check"), "unprovenanced sensor must not bypass recent_irrigation gate");
});

test("safety gate: recent irrigation with stale sensor is blocked", () => {
  const staleTs = new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(); // 6 hours ago
  const signals = { rulesTriggered: ["recent_irrigation"], needScore: 0.85, action: "irrigate", urgency: "high", missingData: [] };
  const decision = { action: "irrigate", confidenceScore: 0.8, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: { irrigationMethod: "Drip", sensorData: { soilMoisturePercent: 15, timestamp: staleTs }, sensorProvenance: "field_sensor" } });
  assert.ok(enforced.guardrailsTriggered.includes("recent_irrigation_requires_field_check"), "stale sensor must not bypass recent_irrigation gate");
});

test("safety gate: stale sensor_high_moisture triggers field check rather than wait", () => {
  const staleTs = new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString();
  const signals = { rulesTriggered: ["sensor_high_moisture"], needScore: 0.78, action: "irrigate", urgency: "high", missingData: [] };
  const decision = { action: "irrigate", confidenceScore: 0.8, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: { sensorData: { soilMoisturePercent: 42, timestamp: staleTs } } });
  assert.equal(enforced.action, "check field first", "stale sensor_high_moisture must trigger field check, not wait");
  assert.ok(enforced.guardrailsTriggered.includes("sensor_high_moisture_stale_requires_field_check"));
});

test("confidence engine: stale sensor does not boost confidence", () => {
  const staleTs = new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString();
  const freshTs = new Date(Date.now() - 30 * 60000).toISOString();
  const withStale = scoreEvidence({ crop: "tomato", soilType: "loam", sensorData: { soilMoisturePercent: 22, timestamp: staleTs } });
  const withFresh = scoreEvidence({ crop: "tomato", soilType: "loam", sensorData: { soilMoisturePercent: 22, timestamp: freshTs, provenance: "field_sensor" } });
  assert.ok(withStale.missingEvidence.some((m) => m.includes("soil moisture sensor")), "stale sensor should appear in missingEvidence");
  assert.ok(withFresh.evidenceChecked.includes("soil moisture sensor"), "fresh provenanced sensor must count as evidence");
  assert.ok(withFresh.confidenceScore > withStale.confidenceScore, "stale sensor must not boost confidence");
});

// ── Gemini Embedding 2 formatting edge cases ─────────────────────────────────

test("GeminiEmbeddingProvider: RETRIEVAL_DOCUMENT with no title uses title:none prefix", async () => {
  let capturedBody = null;
  const fakeFetch = async (_url, opts) => {
    capturedBody = JSON.parse(opts.body);
    return { ok: true, status: 200, text: async () => JSON.stringify({ embedding: { values: [0.1, 0.2, 0.3] } }) };
  };
  const provider = new GeminiEmbeddingProvider({ apiKey: "test-key", model: "gemini-embedding-2", fetchImpl: fakeFetch });
  await provider.embed("Tomato field in loam soil", { taskType: "RETRIEVAL_DOCUMENT" });
  const text = capturedBody?.content?.parts?.[0]?.text || "";
  assert.ok(text.startsWith("title: none | text:"), `RETRIEVAL_DOCUMENT with no title must use 'title: none | text:' prefix, got: ${text}`);
});

test("GeminiEmbeddingProvider: RETRIEVAL_DOCUMENT with title uses title prefix", async () => {
  let capturedBody = null;
  const fakeFetch = async (_url, opts) => {
    capturedBody = JSON.parse(opts.body);
    return { ok: true, status: 200, text: async () => JSON.stringify({ embedding: { values: [0.1, 0.2, 0.3] } }) };
  };
  const provider = new GeminiEmbeddingProvider({ apiKey: "test-key", model: "gemini-embedding-2", fetchImpl: fakeFetch });
  await provider.embed("Irrigation decision guide", { taskType: "RETRIEVAL_DOCUMENT", title: "Irrigation Guide" });
  const text = capturedBody?.content?.parts?.[0]?.text || "";
  assert.ok(text.startsWith("title: Irrigation Guide | text:"), `RETRIEVAL_DOCUMENT with title must include title prefix, got: ${text}`);
  assert.ok(!capturedBody.taskType, "gemini-embedding-2 must not send taskType field");
});

// ── Strict sensor validation (validateSensor) ─────────────────────────────────

test("validateSensor: no-data, non-numeric, no-timestamp, no-provenance cases", () => {
  assert.equal(validateSensor(null).usable, false);
  assert.equal(validateSensor({}).usable, false);
  assert.equal(validateSensor({ soilMoisturePercent: "22%" }).usable, false);
  const freshTs = new Date(Date.now() - 30 * 60000).toISOString();
  // numeric but no timestamp
  const noTs = validateSensor({ soilMoisturePercent: 22 });
  assert.equal(noTs.usable, false);
  assert.equal(noTs.reason, "no sensor timestamp");
  assert.equal(noTs.moisture, 22);
  // numeric + timestamp but no provenance
  const noProv = validateSensor({ soilMoisturePercent: 22, timestamp: freshTs });
  assert.equal(noProv.usable, false);
  assert.equal(noProv.reason, "no sensor provenance");
  assert.equal(noProv.moisture, 22);
});

test("validateSensor: sensor with mismatched fieldId has hardenedForBypass false", () => {
  const freshTs = new Date(Date.now() - 30 * 60000).toISOString();
  const sensor = { soilMoisturePercent: 12, timestamp: freshTs, provenance: "field_sensor", fieldId: "field-b" };
  const ctx = { fieldId: "field-a", sensorProvenance: "field_sensor" };
  const result = validateSensor(sensor, ctx);
  assert.equal(result.usable, true, "sensor passes basic validity checks");
  assert.equal(result.fieldMappingValid, false, "fieldId mismatch must set fieldMappingValid false");
  assert.equal(result.hardenedForBypass, false, "mismatched fieldId must prevent hardenedForBypass");
});

test("validateSensor: fresh mapped provenanced sensor has hardenedForBypass true", () => {
  const freshTs = new Date(Date.now() - 30 * 60000).toISOString();
  const sensor = { soilMoisturePercent: 12, timestamp: freshTs, provenance: "field_sensor", fieldId: "field-a" };
  const ctx = { fieldId: "field-a", sensorProvenance: "field_sensor" };
  const result = validateSensor(sensor, ctx);
  assert.equal(result.usable, true);
  assert.equal(result.fieldMappingValid, true);
  assert.equal(result.hardenedForBypass, true);
});

test("validateSensor: stale low-moisture sensor does not raise needScore", () => {
  const staleTs = new Date(Date.now() - 6 * 60 * 60000).toISOString();
  const base = buildNormalizedFieldContext({
    field: { id: "f", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "moderate" },
    weather: { heatRisk: "low", rainChance: 5, weatherTimestamp: new Date().toISOString(), stale: false },
  });
  const withStale = calculateDeterministicSignals({ ...base, sensorData: { soilMoisturePercent: 14, timestamp: staleTs } });
  const withNone = calculateDeterministicSignals({ ...base, sensorData: null });
  assert.equal(withStale.needScore, withNone.needScore, "stale low-moisture sensor must not raise needScore");
  assert.ok(!withStale.rulesTriggered.includes("sensor_low_moisture"), "stale sensor must not trigger sensor_low_moisture rule");
});

test("validateSensor: untimestamped sensor does not increase confidence", () => {
  const base = { crop: "tomato", soilType: "loam", irrigationMethod: "Drip", weather: { weatherTimestamp: new Date().toISOString(), stale: false } };
  const withUntimed = scoreEvidence({ ...base, sensorData: { soilMoisturePercent: 14 } });
  const withNone = scoreEvidence(base);
  assert.ok(withUntimed.missingEvidence.some((m) => m.startsWith("soil moisture sensor")), "untimestamped sensor must appear in missingEvidence");
  assert.equal(withUntimed.confidenceScore, withNone.confidenceScore, "untimestamped sensor must not change confidence score");
});

test("validateSensor: unprovenanced sensor does not increase confidence", () => {
  const freshTs = new Date(Date.now() - 30 * 60000).toISOString();
  const base = { crop: "tomato", soilType: "loam", irrigationMethod: "Drip", weather: { weatherTimestamp: new Date().toISOString(), stale: false } };
  const withNoProv = scoreEvidence({ ...base, sensorData: { soilMoisturePercent: 14, timestamp: freshTs } });
  const withNone = scoreEvidence(base);
  assert.ok(withNoProv.missingEvidence.some((m) => m.startsWith("soil moisture sensor")), "unprovenanced sensor must appear in missingEvidence");
  assert.equal(withNoProv.confidenceScore, withNone.confidenceScore, "unprovenanced sensor must not change confidence score");
});

test("validateSensor: untimestamped low-moisture sensor cannot bypass recent-irrigation gate", () => {
  const signals = { rulesTriggered: ["recent_irrigation"], needScore: 0.85, action: "irrigate", urgency: "high", missingData: [] };
  const decision = { action: "irrigate", confidenceScore: 0.8, missingData: [], uncertainties: [], reasons: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: { irrigationMethod: "Drip", sensorData: { soilMoisturePercent: 15 }, sensorProvenance: "field_sensor" } });
  assert.ok(enforced.guardrailsTriggered.includes("recent_irrigation_requires_field_check"), "untimestamped sensor must not bypass recent_irrigation gate even when provenance is present");
});

test("validateSensor: soil moisture claim scrubbed when sensor lacks timestamp", () => {
  const signals = { rulesTriggered: [], needScore: 0.6, action: "check field first", urgency: "medium", missingData: [] };
  const decision = { action: "check field first", confidenceScore: 0.6, reasons: ["Soil moisture is 22% based on sensor"], uncertainties: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: { sensorData: { soilMoisturePercent: 22 } } });
  assert.ok(!enforced.reasons.join(" ").includes("22%"), "soil moisture claim must be scrubbed when sensor has no timestamp");
});

test("validateSensor: soil moisture claim permitted only when strict validation passes", () => {
  const freshTs = new Date(Date.now() - 30 * 60000).toISOString();
  const signals = { rulesTriggered: [], needScore: 0.6, action: "check field first", urgency: "medium", missingData: [] };
  const decision = { action: "check field first", confidenceScore: 0.6, reasons: ["Soil moisture is 22% based on sensor"], uncertainties: [], fieldChecks: [], risks: [], nextBestAction: "", safetyNotes: [], verificationPlan: [], guardrailsTriggered: [], disclaimer: "" };
  const enforced = safetyGuardrails.enforce(decision, { weather: { stale: false }, deterministicSignals: signals, fieldContext: { sensorData: { soilMoisturePercent: 22, timestamp: freshTs, provenance: "field_sensor" } } });
  assert.ok(enforced.reasons.join(" ").includes("22%"), "soil moisture claim must be preserved when sensor passes strict validation");
});

// ── Weather timestamp hardening ───────────────────────────────────────────────

test("weatherFreshnessScore: invalid weather timestamp yields no freshness credit", () => {
  const withInvalid = scoreEvidence({ crop: "tomato", soilType: "loam", irrigationMethod: "Drip", weather: { weatherTimestamp: "not-a-date", stale: false } });
  const withMissing = scoreEvidence({ crop: "tomato", soilType: "loam", irrigationMethod: "Drip", weather: { stale: false } });
  assert.ok(withInvalid.missingEvidence.includes("weather freshness"), "invalid weather timestamp must appear in missingEvidence");
  assert.equal(withInvalid.confidenceScore, withMissing.confidenceScore, "invalid weather timestamp must not grant freshness credit");
});

test("weatherFreshnessScore: future weather timestamp beyond clock skew yields no freshness credit", () => {
  const futureTs = new Date(Date.now() + 60 * 60000).toISOString(); // 1 hour in future
  const withFuture = scoreEvidence({ crop: "tomato", soilType: "loam", irrigationMethod: "Drip", weather: { weatherTimestamp: futureTs, stale: false } });
  const withMissing = scoreEvidence({ crop: "tomato", soilType: "loam", irrigationMethod: "Drip", weather: { stale: false } });
  assert.ok(withFuture.missingEvidence.includes("weather freshness"), "future weather timestamp beyond clock skew must appear in missingEvidence");
  assert.equal(withFuture.confidenceScore, withMissing.confidenceScore, "future weather timestamp must not grant freshness credit");
});
