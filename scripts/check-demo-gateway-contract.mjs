import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync("cloudflare/form-notification-gateway/src/index.js", "utf8");
const worker = (await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"))).default;
const endpoint = "https://agroai-pilot.com/api/demo-request";
const backend = "https://api.agroai-pilot.com/v1/sales/contact";

async function submit(backendResult, expected) {
  let calls = 0;
  globalThis.fetch = async (url, init) => {
    assert.equal(String(url), backend);
    assert.equal(init.method, "POST");
    const payload = JSON.parse(init.body);
    assert.equal(payload.email, "sales-qa@example.test");
    calls++;
    if (backendResult === "network") throw new Error("network unavailable");
    return Response.json(backendResult, { status: 200 });
  };
  const response = await worker.fetch(new Request(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      fullName: "Sales QA",
      email: "sales-qa@example.test",
      farmName: "Demo Farm",
      location: "California",
    }),
  }));
  assert.equal(calls, 1);
  assert.equal(response.status, expected.http);
  assert.equal(response.headers.get("x-agroai-notification"), expected.mail);
  const json = await response.json();
  if (expected.id) assert.equal(json.id, "stored-123");
  if (expected.saved) {
    assert.equal(json.saved, true);
    assert.equal(response.headers.get("x-agroai-lead-persisted"), "true");
  }
  if (expected.failed) {
    assert.equal(json.error, "notification_delivery_failed");
    assert.notEqual(response.headers.get("x-agroai-lead-persisted"), "true");
  }
}

for (const emailStatus of ["emailed", "emailed:contact@agroai-pilot.com"]) {
  await submit({
    status: "received", request_id: "stored-123", notification_status: emailStatus,
  }, { http: 201, mail: "delivered", id: true });
}
for (const emailStatus of ["email_not_configured", "email_failed:provider_rejected"]) {
  await submit({
    status: "received", request_id: "stored-123", notification_status: emailStatus,
  }, { http: 202, mail: "pending", id: true, saved: true });
}
await submit({ status: "received", notification_status: "emailed" },
  { http: 502, mail: "failed", failed: true });
await submit("network", { http: 502, mail: "failed", failed: true });

// Unauthorized or invalid leads cannot trigger external calls.
globalThis.fetch = async () => { throw new Error("invalid lead called upstream"); };
const invalid = await worker.fetch(new Request(endpoint, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ fullName: "Invalid", email: "wrong" }),
}));
assert.equal(invalid.status, 400);
const careersGet = await worker.fetch(new Request("https://agroai-pilot.com/api/apply"));
assert.equal(careersGet.status, 200);
assert.equal((await careersGet.json()).ok, true);
console.log("Gateway email-status and durable-lead contract passed.");
