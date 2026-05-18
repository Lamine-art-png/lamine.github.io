import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { app } from "../server.js";

async function withServer(run) {
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, resolve));
  const { port } = server.address();
  const base = `http://127.0.0.1:${port}`;
  try {
    await run(base);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

test("health endpoint", async () => {
  await withServer(async (base) => {
    const res = await fetch(`${base}/health`);
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.ok, true);
  });
});

test("decision endpoint returns decision", async () => {
  await withServer(async (base) => {
    const res = await fetch(`${base}/v1/decisions/daily`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        field: { id: "f1", crop: "grape", waterStressLevel: "moderate" },
        weather: { forecastSummary: "hot", rainChance: 10, heatRisk: "elevated", frostRisk: "low" },
        observations: [{ condition: "Looks dry" }],
      }),
    });
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.type, "decision");
    assert.ok(body.decision.action);
  });
});

test("assistant, voice, memory, weather, evaluation endpoints", async () => {
  await withServer(async (base) => {
    const assistant = await fetch(`${base}/v1/assistant/query`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ decision: { confidenceScore: 0.5, reasons: ["mock reason"] } }),
    });
    assert.equal(assistant.status, 200);

    const voice = await fetch(`${base}/v1/voice/interpret`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ transcript: "Log irrigation for two hours", fieldId: "f1" }),
    });
    const voiceBody = await voice.json();
    assert.equal(voice.status, 200);
    assert.equal(voiceBody.intent, "LOG_IRRIGATION");

    const weather = await fetch(`${base}/v1/weather/context`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ location: "Napa" }),
    });
    assert.equal(weather.status, 200);

    const memory = await fetch(`${base}/v1/memory/update`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ fieldId: "f1", event: { type: "voice", payload: { transcript: "hello" } } }),
    });
    assert.equal(memory.status, 200);

    const evalRes = await fetch(`${base}/v1/evaluation/run`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ decision: { action: "monitor", confidenceScore: 0.4, missingData: [], reasons: ["x"], disclaimer: "y" } }),
    });
    assert.equal(evalRes.status, 200);
  });
});
