import test from "node:test";
import assert from "node:assert/strict";
import { PassThrough, Writable } from "node:stream";

process.env.NODE_ENV = "test";
const { app } = await import("../server.js");

function invokeApp(method, path, body = null) {
  return new Promise((resolve, reject) => {
    // Serialize body first so we can set content-length before creating the stream.
    // Express body-parser requires content-length to parse a pre-ended PassThrough
    // stream (it does not read until EOF from a stream that lacks transfer-encoding).
    const bodyStr = body ? JSON.stringify(body) : null;

    const req = new PassThrough();
    req.method = method;
    req.url = path;
    req.headers = {
      "content-type": "application/json",
      ...(bodyStr ? { "content-length": String(Buffer.byteLength(bodyStr)) } : {}),
    };
    // Express's setPrototypeOf(req, IncomingMessage) later calls eos(socket) in
    // _destroy — eos requires instanceof Stream, so socket must be a real stream.
    const socketMock = new PassThrough();
    socketMock.remoteAddress = "127.0.0.1";
    req.socket = socketMock;

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
    res.status = (code) => { res.statusCode = code; return res; };
    res.json = (obj) => { res.end(JSON.stringify(obj)); };
    res.end = (chunk) => {
      if (chunk) chunks.push(Buffer.from(chunk));
      const text = Buffer.concat(chunks).toString("utf8");
      resolve({ status: res.statusCode, body: text ? JSON.parse(text) : null });
    };

    // Write body before calling app — Express's setPrototypeOf replaces the
    // PassThrough prototype chain (removing Writable methods like end()),
    // so we must write/end the stream before handing it to Express.
    if (bodyStr) req.end(bodyStr);
    else req.end();
    Promise.resolve(app(req, res)).catch(reject);
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
