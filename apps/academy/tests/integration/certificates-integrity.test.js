// Certificate verification fails closed: a credential is shown as valid only
// after its signature is recomputed and matches.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv, Client, registeredLearner, publishCourse, completeA1, withSettings } from "../helpers.js";
import { config } from "../../src/app.js";

const STRONG = "a".repeat(16) + "-strong-signing-secret-for-tests-0123456789";

async function certifiedEnv() {
  const env = makeEnv({ CERT_SIGNING_SECRET: STRONG });
  await publishCourse(env, "crs_a1");
  const learner = await registeredLearner(env, { email: "ines@academy.test", name: "Inês Moreira" });
  const { user, cert } = await completeA1(env, learner);
  assert.ok(cert, "certificate issued with a configured signing key");
  return { env, learner, user, cert };
}

test("signing configuration: only development and tests have a built-in key", () => {
  const u = new URL("https://x.test/");
  assert.equal(config({ ENVIRONMENT: "development" }, u).certSigning, "configured");
  assert.equal(config({ ENVIRONMENT: "test" }, u).certSigning, "configured");
  for (const environment of ["staging", "production"]) {
    const missing = config({ ENVIRONMENT: environment }, u);
    assert.equal(missing.certSigning, "not_configured", `${environment} has no fallback key`);
    assert.equal(missing.certSecret, null);
    const short = config({ ENVIRONMENT: environment, CERT_SIGNING_SECRET: "too-short" }, u);
    assert.equal(short.certSigning, "too_short");
    assert.equal(short.certSecret, null);
    assert.equal(config({ ENVIRONMENT: environment, CERT_SIGNING_SECRET: STRONG }, u).certSigning, "configured");
  }
});

test("a correctly signed active credential verifies as valid", async () => {
  const { env, cert } = await certifiedEnv();
  const r = await new Client(env).get(`/verify/${cert.credential_id}`);
  assert.equal(r.status, 200);
  assert.match(r.text, /data-verify-state="valid"/);
  assert.match(r.text, /Valid credential/);
  assert.match(r.text, /EducationalOccupationalCredential/);
});

test("missing or weak signing configuration never shows a credential as valid", async () => {
  const { env, cert, learner } = await certifiedEnv();
  const cases = {
    "production without a key": { ENVIRONMENT: "production", CERT_SIGNING_SECRET: undefined },
    "staging without a key": { ENVIRONMENT: "staging", CERT_SIGNING_SECRET: undefined },
    "production with a short key": { ENVIRONMENT: "production", CERT_SIGNING_SECRET: "short" },
  };
  for (const [name, overrides] of Object.entries(cases)) {
    const broken = withSettings(env, overrides);
    const r = await new Client(broken).get(`/verify/${cert.credential_id}`);
    assert.equal(r.status, 503, name);
    assert.equal(r.headers.get("retry-after"), "300");
    assert.match(r.text, /Verification temporarily unavailable/, name);
    assert.doesNotMatch(r.text, /Valid credential|data-verify-state="valid"|EducationalOccupationalCredential/, name);
    assert.doesNotMatch(r.text, /class="certificate/, `${name}: no certificate visual`);

    const health = await new Client(broken).get("/healthz");
    assert.equal(health.status, 503, `${name}: health check fails`);
    const h = JSON.parse(health.text);
    assert.equal(h.ok, false);
    assert.notEqual(h.certificate_signing, "configured");

    // The owner sees a warning and cannot download a PDF.
    const owner = Object.assign(new Client(broken), { jar: learner.jar });
    const page = await owner.get(`/certificates/${cert.credential_id}`);
    assert.equal(page.status, 200);
    assert.doesNotMatch(page.text, /\/pdf" download/);
    const pdf = await owner.get(`/certificates/${cert.credential_id}/pdf`);
    assert.equal(pdf.status, 503);
  }
});

test("a tampered record or a different key fails the integrity check", async () => {
  const { env, cert, learner } = await certifiedEnv();
  await env.DB.prepare("UPDATE certificates SET credential_name = 'Someone Else' WHERE id = ?").bind(cert.id).run();
  let r = await new Client(env).get(`/verify/${cert.credential_id}`);
  assert.equal(r.status, 200);
  assert.match(r.text, /data-verify-state="integrity_failed"/);
  assert.match(r.text, /could not be validated/);
  assert.doesNotMatch(r.text, /Valid credential|EducationalOccupationalCredential/);
  const pdf = await learner.get(`/certificates/${cert.credential_id}/pdf`);
  assert.equal(pdf.status, 409);

  await env.DB.prepare("UPDATE certificates SET credential_name = ?, signature = '' WHERE id = ?").bind(cert.credential_name, cert.id).run();
  r = await new Client(env).get(`/verify/${cert.credential_id}`);
  assert.match(r.text, /data-verify-state="integrity_failed"/, "empty signature is invalid");

  await env.DB.prepare("UPDATE certificates SET signature = ? WHERE id = ?").bind(cert.signature, cert.id).run();
  const rotated = withSettings(env, { CERT_SIGNING_SECRET: "b".repeat(64) });
  r = await new Client(rotated).get(`/verify/${cert.credential_id}`);
  assert.match(r.text, /data-verify-state="integrity_failed"/, "signature from another key is invalid");
});

test("revoked credentials are reported as revoked, never valid", async () => {
  const { env, cert } = await certifiedEnv();
  await env.DB.prepare("UPDATE certificates SET status = 'revoked', revoked_at = ? WHERE id = ?").bind(new Date().toISOString(), cert.id).run();
  const r = await new Client(env).get(`/verify/${cert.credential_id}`);
  assert.match(r.text, /data-verify-state="revoked"/);
  assert.doesNotMatch(r.text, /EducationalOccupationalCredential/);
});

test("without a signing key no credential is issued, and progress is kept", async () => {
  const env = makeEnv({ ENVIRONMENT: "staging", CERT_SIGNING_SECRET: undefined });
  delete env.CERT_SIGNING_SECRET;
  await publishCourse(env, "crs_a1");
  const learner = await registeredLearner(env, { email: "kofi@academy.test", name: "Kofi Mensah" });
  const { user, cert } = await completeA1(env, learner);
  assert.equal(cert, null, "no unsigned credential");
  const enr = await env.DB.prepare("SELECT status FROM enrollments WHERE user_id = ?").bind(user.id).first();
  assert.equal(enr.status, "completed", "course completion still recorded");
  // Once the key is configured, the learner claims the credential.
  const fixed = withSettings(env, { CERT_SIGNING_SECRET: STRONG });
  const claimer = Object.assign(new Client(fixed), { jar: learner.jar, csrf: learner.csrf });
  const r = await claimer.post("/certificates/claim/introduction-to-ai-in-agriculture", {});
  assert.match(r.location, /^\/certificates\/AGA-/);
});
