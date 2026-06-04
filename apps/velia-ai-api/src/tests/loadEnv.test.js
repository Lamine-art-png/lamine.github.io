import test from "node:test";
import assert from "node:assert/strict";
import { PassThrough, Writable } from "node:stream";
import { loadDotenv } from "../loadEnv.js";

// Must be set before server.js is evaluated so it does not attempt to bind a port.
process.env.NODE_ENV = "test";
const { createFallbackApp } = await import("../server.js");

// ── loadDotenv unit tests ─────────────────────────────────────────────────────

test("loadDotenv: loads successfully when dotenv is available", async () => {
  let called = false;
  await assert.doesNotReject(
    loadDotenv(async () => { called = true; }),
    "loadDotenv must resolve when importFn succeeds",
  );
  assert.ok(called, "importFn must be invoked");
});

test("loadDotenv: does not crash when dotenv is absent (MODULE_NOT_FOUND)", async () => {
  const absent = (code) => async () => {
    const err = new Error("Cannot find module 'dotenv/config'");
    err.code = code;
    throw err;
  };
  await assert.doesNotReject(
    loadDotenv(absent("MODULE_NOT_FOUND")),
    "CJS-style MODULE_NOT_FOUND must be silently tolerated",
  );
  await assert.doesNotReject(
    loadDotenv(absent("ERR_MODULE_NOT_FOUND")),
    "ESM-style ERR_MODULE_NOT_FOUND must be silently tolerated",
  );
});

test("loadDotenv: does not swallow unrelated import errors", async () => {
  const unrelated = async () => {
    const err = new Error("Unexpected module evaluation failure");
    err.code = "ERR_MODULE_EVALUATION_FAILURE";
    throw err;
  };
  await assert.rejects(
    loadDotenv(unrelated),
    { code: "ERR_MODULE_EVALUATION_FAILURE" },
    "non-MODULE_NOT_FOUND errors must propagate",
  );
});

// ── native fallback /health ───────────────────────────────────────────────────

test("native fallback: /health works in dependency-light mode", async () => {
  const handler = createFallbackApp();

  const req = new PassThrough();
  req.method = "GET";
  req.url = "/health";
  req.headers = {};
  const socketMock = new PassThrough();
  socketMock.remoteAddress = "127.0.0.1";
  req.socket = socketMock;
  req.end();

  const result = await new Promise((resolve, reject) => {
    const chunks = [];
    const res = new Writable({
      write(chunk, _enc, cb) { chunks.push(Buffer.from(chunk)); cb(); },
    });
    res.statusCode = 200;
    res.headers = {};
    res.writeHead = (status, headers = {}) => { res.statusCode = status; res.headers = headers; };
    res.end = (chunk) => {
      if (chunk) chunks.push(Buffer.from(chunk));
      const text = Buffer.concat(chunks).toString("utf8");
      resolve({ status: res.statusCode, body: JSON.parse(text) });
    };
    Promise.resolve(handler(req, res)).catch(reject);
  });

  assert.equal(result.status, 200);
  assert.equal(result.body.ok, true);
  assert.equal(result.body.service, "velia-ai-api");
  assert.equal(result.body.runtime, "node-fallback", "fallback handler must identify itself as node-fallback");
});
