import assert from "node:assert/strict";
import test from "node:test";
import { verifyWebhookSignature } from "../dist/webhooks.js";

test("verifies signature and rejects replay", async () => {
  const secret = "whsec_test";
  const body = '{"event":"field.updated"}';
  const timestamp = "1000";
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const digest = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${timestamp}.${body}`)));
  const signature = [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  assert.equal(await verifyWebhookSignature({ secret, body, timestamp, signature: `v1=${signature}`, nowSeconds: 1001 }), true);
  assert.equal(await verifyWebhookSignature({ secret, body, timestamp, signature, nowSeconds: 2000 }), false);
});
