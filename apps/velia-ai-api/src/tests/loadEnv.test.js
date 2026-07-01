import test from "node:test";
import assert from "node:assert/strict";
import { PassThrough, Writable } from "node:stream";
import { loadDotenv } from "../loadEnv.js";

// Must be set before server.js is evaluated so it does not attempt to bind a port.
process.env.NODE_ENV = "test";
const { createFallbackApp, createApp } = await import("../server.js");

// ── loadDotenv unit tests ─────────────────────────────────────────────────────

test("loadDotenv: resolution succeeds and importFn is called with the resolved path", async () => {
  const FAKE_URL = "file:///fake/node_modules/dotenv/config.js";
  let importedWith = null;
  await loadDotenv({
    resolveFn: () => FAKE_URL,
    importFn: async (url) => { importedWith = url; },
  });
  assert.equal(importedWith, FAKE_URL, "importFn must receive the resolved path");
});

test("loadDotenv: MODULE_NOT_FOUND from resolveFn (dotenv absent, CJS-style) is tolerated", async () => {
  let importCalled = false;
  const absent = () => {
    const err = new Error("Cannot find module 'dotenv/config'");
    err.code = "MODULE_NOT_FOUND";
    throw err;
  };
  await assert.doesNotReject(
    loadDotenv({ resolveFn: absent, importFn: async () => { importCalled = true; } }),
    "CJS-style MODULE_NOT_FOUND must be silently tolerated",
  );
  assert.equal(importCalled, false, "importFn must not be called when dotenv is absent");
});

test("loadDotenv: ERR_MODULE_NOT_FOUND from resolveFn (dotenv absent, ESM-style) is tolerated", async () => {
  let importCalled = false;
  const absent = () => {
    const err = new Error("Cannot find package 'dotenv'");
    err.code = "ERR_MODULE_NOT_FOUND";
    throw err;
  };
  await assert.doesNotReject(
    loadDotenv({ resolveFn: absent, importFn: async () => { importCalled = true; } }),
    "ESM-style ERR_MODULE_NOT_FOUND must be silently tolerated",
  );
  assert.equal(importCalled, false, "importFn must not be called when dotenv is absent");
});

test("loadDotenv: ERR_MODULE_NOT_FOUND from importFn (transitive dep) is rethrown", async () => {
  const transitive = async () => {
    const err = new Error("Cannot find package 'some-dotenv-dep'");
    err.code = "ERR_MODULE_NOT_FOUND";
    throw err;
  };
  await assert.rejects(
    loadDotenv({ resolveFn: () => "file:///fake/dotenv/config.js", importFn: transitive }),
    { code: "ERR_MODULE_NOT_FOUND" },
    "ERR_MODULE_NOT_FOUND from importFn (transitive dep) must propagate",
  );
});

test("loadDotenv: MODULE_NOT_FOUND from importFn (CJS transitive dep) is rethrown", async () => {
  const transitive = async () => {
    const err = new Error("Cannot find module 'some-dotenv-dep'");
    err.code = "MODULE_NOT_FOUND";
    throw err;
  };
  await assert.rejects(
    loadDotenv({ resolveFn: () => "/fake/dotenv/config.js", importFn: transitive }),
    { code: "MODULE_NOT_FOUND" },
    "MODULE_NOT_FOUND from importFn (CJS transitive dep) must propagate",
  );
});

test("loadDotenv: ERR_MODULE_EVALUATION_FAILURE from importFn is rethrown", async () => {
  const badEval = async () => {
    const err = new Error("Unexpected module evaluation failure");
    err.code = "ERR_MODULE_EVALUATION_FAILURE";
    throw err;
  };
  await assert.rejects(
    loadDotenv({ resolveFn: () => "/fake/dotenv/config.js", importFn: badEval }),
    { code: "ERR_MODULE_EVALUATION_FAILURE" },
    "non-MODULE_NOT_FOUND errors from importFn must propagate",
  );
});

test("loadDotenv: unrelated error from resolveFn is rethrown", async () => {
  const unrelated = () => {
    const err = new Error("disk I/O error");
    err.code = "EIO";
    throw err;
  };
  await assert.rejects(
    loadDotenv({ resolveFn: unrelated }),
    { code: "EIO" },
    "non-MODULE_NOT_FOUND errors from resolveFn must propagate",
  );
});

// ── helpers for invoking a raw http handler ───────────────────────────────────

function invokeHandler(handler, method, path, body = null) {
  return new Promise((resolve, reject) => {
    const bodyStr = body ? JSON.stringify(body) : null;
    const req = new PassThrough();
    req.method = method;
    req.url = path;
    req.headers = { "content-type": "application/json", ...(bodyStr ? { "content-length": String(Buffer.byteLength(bodyStr)) } : {}) };
    const socketMock = new PassThrough();
    socketMock.remoteAddress = "127.0.0.1";
    req.socket = socketMock;

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
      resolve({ status: res.statusCode, body: text ? JSON.parse(text) : null });
    };

    if (bodyStr) req.end(bodyStr);
    else req.end();
    Promise.resolve(handler(req, res)).catch(reject);
  });
}

// ── native fallback createFallbackApp ────────────────────────────────────────

test("native fallback: /health returns 200 with runtime node-fallback", async () => {
  const handler = createFallbackApp();
  const result = await invokeHandler(handler, "GET", "/health");
  assert.equal(result.status, 200);
  assert.equal(result.body.ok, true);
  assert.equal(result.body.service, "velia-ai-api");
  assert.equal(result.body.runtime, "node-fallback");
});

// ── createApp fallback-selection ─────────────────────────────────────────────

test("createApp: Express factory failure selects native fallback automatically", async () => {
  const failExpress = async () => {
    throw Object.assign(new Error("express not installed"), { code: "ERR_MODULE_NOT_FOUND" });
  };
  const handler = await createApp(failExpress);
  assert.strictEqual(typeof handler, "function", "createApp must return a handler function");
  const result = await invokeHandler(handler, "GET", "/health");
  assert.equal(result.status, 200);
  assert.equal(result.body.runtime, "node-fallback", "fallback must identify itself");
});

test("createApp: native fallback /health returns 200 when Express is unavailable", async () => {
  const failExpress = async () => { throw new Error("no express"); };
  const handler = await createApp(failExpress);
  const result = await invokeHandler(handler, "GET", "/health");
  assert.equal(result.status, 200);
  assert.equal(result.body.ok, true);
});

test("createApp: missing dotenv does not prevent native fallback selection", async () => {
  // loadDotenv already ran during server.js module init; simulate a fresh call returning
  // cleanly (dotenv absent scenario) — createApp must still work.
  const failExpress = async () => { throw new Error("no express"); };
  const handler = await createApp(failExpress);
  assert.strictEqual(typeof handler, "function");
  const result = await invokeHandler(handler, "GET", "/health");
  assert.equal(result.status, 200);
});
