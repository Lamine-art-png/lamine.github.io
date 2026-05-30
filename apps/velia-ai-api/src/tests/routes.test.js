import test from "node:test";
import assert from "node:assert/strict";
import { PassThrough, Writable } from "node:stream";

process.env.NODE_ENV = "test";
const { app } = await import("../server.js");

function invokeApp(method, path, body = null) {
  return new Promise((resolve, reject) => {
    const req = new PassThrough();
    req.method = method;
    req.url = path;
    req.headers = { "content-type": "application/json" };

    const chunks = [];
    const res = new Writable({
      write(chunk, _encoding, callback) {
        chunks.push(Buffer.from(chunk));
        callback();
      },
    });
    res.statusCode = 200;
    res.headers = {};
    res.writeHead = (status, headers = {}) => {
      res.statusCode = status;
      res.headers = headers;
    };
    res.setHeader = (key, value) => {
      res.headers[key.toLowerCase()] = value;
    };
    res.getHeader = (key) => res.headers[key.toLowerCase()];
    res.end = (chunk) => {
      if (chunk) chunks.push(Buffer.from(chunk));
      const text = Buffer.concat(chunks).toString("utf8");
      resolve({ status: res.statusCode, body: text ? JSON.parse(text) : null });
    };

    Promise.resolve(app(req, res)).catch(reject);
    if (body) req.end(JSON.stringify(body));
    else req.end();
  });
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

test("assistant, voice, memory, weather, evaluation endpoints", async () => {
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
});
