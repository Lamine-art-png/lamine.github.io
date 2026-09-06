import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";

process.env.NODE_ENV = "test";
const { app } = await import("../server.js");

async function invokeApp(method, path, body = null) {
  const server = http.createServer(app);
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });

  try {
    const address = server.address();
    const response = await fetch("http://127.0.0.1:" + address.port + path, {
      method,
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await response.text();
    return { status: response.status, body: text ? JSON.parse(text) : null };
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

test("health endpoint", async () => {
  const res = await invokeApp("GET", "/health");
  assert.equal(res.status, 200);
  assert.equal(res.body.ok, true);
});

test("decision endpoint returns decision", async () => {
  const res = await invokeApp("POST", "/v1/decisions/daily", {
    field: { id: "f1", crop: "grape", waterStressLevel: "moderate" },
    weather: { forecastSummary: "hot", rainChance: 10, heatRisk: "elevated", frostRisk: "low", weatherTimestamp: new Date().toISOString() },
    observations: [{ condition: "Looks dry" }],
  });
  assert.equal(res.status, 200);
  assert.equal(res.body.type, "decision");
  assert.ok(res.body.decision.action);
  assert.ok(res.body.decision.provenance);
});

test("assistant, voice, memory, weather, evaluation, and model status endpoints", async () => {
  const assistant = await invokeApp("POST", "/v1/assistant/query", {
    query: "Why?",
    decision: { confidenceScore: 0.5, confidenceLabel: "moderate", reasons: ["grounded reason"], missingData: [], fieldChecks: [], provenance: { decisionTimestamp: new Date().toISOString(), ragSourcesUsed: [] } },
  });
  assert.equal(assistant.status, 200);

  const voice = await invokeApp("POST", "/v1/voice/interpret", { transcript: "Log irrigation for two hours", fieldId: "f1" });
  assert.equal(voice.status, 200);
  assert.equal(voice.body.intent, "LOG_IRRIGATION");

  const weather = await invokeApp("POST", "/v1/weather/context", { location: "Napa" });
  assert.equal(weather.status, 200);

  const memory = await invokeApp("POST", "/v1/memory/update", { fieldId: "f1", event: { type: "voice", payload: { transcript: "hello" } } });
  assert.equal(memory.status, 200);

  const evalRes = await invokeApp("POST", "/v1/evaluation/run", {
    decision: {
      action: "monitor",
      confidenceScore: 0.4,
      missingData: [],
      uncertainties: [],
      reasons: ["x"],
      disclaimer: "y",
      guardrailWarnings: [],
      knowledgeSources: [],
      verificationPlan: {},
      provenance: {
        decisionTimestamp: new Date().toISOString(),
        dataSourcesChecked: [],
        deterministicRulesTriggered: [],
        fallbackStatus: {},
      },
    },
  });
  assert.equal(evalRes.status, 200);
  assert.ok(evalRes.body.scenarioCount >= 30);

  const modelStatus = await invokeApp("GET", "/v1/model/status");
  assert.equal(modelStatus.status, 200);
  assert.equal(modelStatus.body.policy.deterministicAgronomyFirst, true);
  assert.equal(modelStatus.body.terrisCore.enabled, false);
});
