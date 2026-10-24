import "dotenv/config";
import { modelRouter } from "../../ai/modelRouter.js";
import { buildNormalizedFieldContext, calculateDeterministicSignals, deterministicDecisionFromSignals } from "../../ai/deterministicIrrigation.js";
import { decisionResponseSchema, parseDecisionJson, validateDecisionResponse } from "../../ai/decisionSchema.js";

const provider = modelRouter.llmProvider();
if (provider.mode !== "live") {
  console.error(`SMOKE FAIL: No live LLM provider configured. Set LLM_PROVIDER and the corresponding API key in .env.`);
  console.error(`  LLM_PROVIDER=${process.env.LLM_PROVIDER || "(not set)"}`);
  process.exit(1);
}
console.log(`Provider: ${provider.name}  model: ${provider.model}  mode: ${provider.mode}`);

const ctx = buildNormalizedFieldContext({
  field: { id: "smoke-field", name: "Smoke Field", crop: "tomato", soilType: "loam", irrigationMethod: "Drip", waterStressLevel: "moderate", lastIrrigationAt: new Date(Date.now() - 4 * 86400000).toISOString() },
  weather: { temperature: 30, rainChance: 12, rainfallForecastMm: 0, heatRisk: "elevated", frostRisk: "low", forecastSummary: "Hot and dry", weatherTimestamp: new Date().toISOString(), stale: false },
  logs: [],
  observations: [{ condition: "Looks dry" }],
});
const signals = calculateDeterministicSignals(ctx);
const fallback = deterministicDecisionFromSignals(signals, ctx);
const prompt = `You are Velia. Return only valid JSON matching the schema.

Deterministic signals: ${JSON.stringify({ action: signals.action, needScore: signals.needScore, rulesTriggered: signals.rulesTriggered }, null, 2)}
Schema: ${JSON.stringify(decisionResponseSchema, null, 2)}`;

const start = Date.now();
let result;
try {
  result = await provider.generate(prompt, { task: "irrigation_decision", schema: decisionResponseSchema, schemaName: "velia_irrigation_decision", fallbackDecision: fallback });
} catch (err) {
  console.error(`SMOKE FAIL: Provider error: ${err.message}`);
  process.exit(1);
}
const latencyMs = Date.now() - start;

let parsed, validation;
try {
  parsed = parseDecisionJson(result.text);
  validation = validateDecisionResponse(parsed);
} catch (err) {
  validation = { ok: false, errors: [err.message] };
}

console.log(`Latency   : ${latencyMs} ms`);
console.log(`Structured: ${validation.ok ? "VALID" : "INVALID"}`);
console.log(`Action    : ${parsed?.action || "(none)"}`);
console.log(`Fallback  : no`);
if (!validation.ok) {
  console.error(`Validation errors: ${validation.errors.join("; ")}`);
  process.exit(1);
}
console.log("LLM smoke test passed.");
