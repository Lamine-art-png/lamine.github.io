import assert from "node:assert/strict";
import test from "node:test";
import {
  AgroAIPlatformClient,
  AgroAIPlatformError,
  verifyWebhookSignature,
} from "../dist/index.js";

const jsonResponse = (status, payload, headers = {}) =>
  new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

test("separates server request IDs from reusable client correlation metadata", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const responses = [
    jsonResponse(200, { route: "me" }, {
      "X-Request-Id": "req_server_one",
      "RateLimit-Limit": "100",
      "RateLimit-Remaining": "99",
      "RateLimit-Reset": "1234",
    }),
    jsonResponse(200, { route: "providers" }, {
      "X-Request-Id": "req_server_two",
    }),
  ];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return responses.shift();
  };
  try {
    const client = new AgroAIPlatformClient({
      apiKey: "agro_test_example",
      baseUrl: "https://api.example.test",
    });
    const first = await client.request("GET", "/v1/platform/me", {
      clientCorrelationId: "customer-trace-42",
    });
    const second = await client.request("GET", "/v1/platform/providers", {
      clientCorrelationId: "customer-trace-42",
    });
    assert.equal(first.requestId, "req_server_one");
    assert.equal(second.requestId, "req_server_two");
    assert.notEqual(first.requestId, second.requestId);
    assert.equal(first.clientCorrelationId, "customer-trace-42");
    assert.equal(second.clientCorrelationId, "customer-trace-42");
    assert.deepEqual(
      calls.map((call) => call.options.headers["X-Request-Id"]),
      ["customer-trace-42", "customer-trace-42"],
    );
    assert.deepEqual(first.rateLimit, {
      limit: 100,
      remaining: 99,
      reset: 1234,
      retryAfter: undefined,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("GET retry reuses only correlation metadata and reports final server ID", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const responses = [
    jsonResponse(503, { code: "temporary" }),
    jsonResponse(200, { ok: true }, { "X-Request-Id": "req_final_attempt" }),
  ];
  globalThis.fetch = async (_url, options) => {
    calls.push(options);
    return responses.shift();
  };
  try {
    const client = new AgroAIPlatformClient({ apiKey: "agro_test_example" });
    const result = await client.request("GET", "/v1/platform/me");
    assert.equal(calls.length, 2);
    assert.equal(calls[0].headers["X-Request-Id"], calls[1].headers["X-Request-Id"]);
    assert.match(calls[0].headers["X-Request-Id"], /^corr_/);
    assert.equal(result.requestId, "req_final_attempt");
    assert.equal(result.clientCorrelationId, calls[0].headers["X-Request-Id"]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("write identity is independent and typed errors retain server ID", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (_url, options) => {
    calls.push(options);
    return jsonResponse(
      409,
      { detail: { code: "idempotency_conflict", message: "payload conflict" } },
      { "X-Request-Id": "req_server_error" },
    );
  };
  try {
    const client = new AgroAIPlatformClient({ apiKey: "agro_test_example" });
    await assert.rejects(
      client.request("POST", "/v1/platform/fields", {
        body: { name: "North" },
        idempotencyKey: "field-create-1",
        clientCorrelationId: "client-write-1",
      }),
      (error) => {
        assert.ok(error instanceof AgroAIPlatformError);
        assert.equal(error.status, 409);
        assert.equal(error.code, "idempotency_conflict");
        assert.equal(error.requestId, "req_server_error");
        return true;
      },
    );
    assert.equal(calls.length, 1);
    assert.equal(calls[0].headers["Idempotency-Key"], "field-create-1");
    assert.equal(calls[0].headers["X-Request-Id"], "client-write-1");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rejects unsafe correlation IDs before network I/O", async () => {
  const originalFetch = globalThis.fetch;
  let called = false;
  globalThis.fetch = async () => {
    called = true;
    return jsonResponse(200, {});
  };
  try {
    const client = new AgroAIPlatformClient({ apiKey: "agro_test_example" });
    await assert.rejects(
      client.request("GET", "/v1/platform/me", {
        clientCorrelationId: "contains spaces",
      }),
      /clientCorrelationId/,
    );
    assert.equal(called, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("field iterator follows opaque cursor pagination", async () => {
  const originalFetch = globalThis.fetch;
  const urls = [];
  const responses = [
    jsonResponse(200, { items: [{ id: "field-1" }], next_cursor: "opaque-next" }),
    jsonResponse(200, { items: [{ id: "field-2" }], next_cursor: null }),
  ];
  globalThis.fetch = async (url) => {
    urls.push(String(url));
    return responses.shift();
  };
  try {
    const client = new AgroAIPlatformClient({
      apiKey: "agro_test_example",
      baseUrl: "https://api.example.test",
    });
    const ids = [];
    for await (const field of client.fields({ pageSize: 25 })) ids.push(field.id);
    assert.deepEqual(ids, ["field-1", "field-2"]);
    assert.match(urls[0], /limit=25/);
    assert.match(urls[1], /cursor=opaque-next/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("verifies webhook signature and rejects replay or tampering", async () => {
  const secret = "whsec_test";
  const body = '{"event":"field.updated"}';
  const timestamp = "1000";
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const digest = new Uint8Array(
    await crypto.subtle.sign(
      "HMAC",
      key,
      new TextEncoder().encode(`${timestamp}.${body}`),
    ),
  );
  const signature = [...digest]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  assert.equal(
    await verifyWebhookSignature({
      secret,
      body,
      timestamp,
      signature: `v1=${signature}`,
      nowSeconds: 1001,
    }),
    true,
  );
  assert.equal(
    await verifyWebhookSignature({
      secret,
      body,
      timestamp,
      signature,
      nowSeconds: 2000,
    }),
    false,
  );
  assert.equal(
    await verifyWebhookSignature({
      secret,
      body: `${body}x`,
      timestamp,
      signature,
      nowSeconds: 1001,
    }),
    false,
  );
});
