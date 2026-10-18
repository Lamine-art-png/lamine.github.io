// Contract tests for the external integrations, exercised as they are wired
// in production but against recorded fakes: Resend email, Google sign-in
// (OAuth 2.0 code flow with PKCE), certificate links, and R2 file uploads.
// These prove the request/response handling; they are not live checks.
import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { makeEnv, Client, registeredLearner, publishCourse, publishDraftUnchecked, completeA1, ORIGIN, tokenFrom } from "../helpers.js";
import { runScheduled } from "../../src/services/jobs.js";

const realFetch = globalThis.fetch;
afterEach(() => (globalThis.fetch = realFetch));

/** Replace outbound fetch; `routes` maps URL prefixes to handlers. Records every call. */
function fakeInternet(routes) {
  const calls = [];
  globalThis.fetch = async (input, init = {}) => {
    const req = new Request(input, init);
    const body = req.method === "GET" ? null : await req.clone().text();
    calls.push({ url: req.url, method: req.method, headers: Object.fromEntries(req.headers), body });
    const handler = Object.entries(routes).find(([prefix]) => req.url.startsWith(prefix))?.[1];
    if (!handler) throw new Error(`unexpected outbound request to ${req.url}`);
    return handler(req, body);
  };
  return calls;
}
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });

// ───────────── Resend ─────────────

const RESEND = { RESEND_API_KEY: "re_contract_test_not_a_real_key", EMAIL_FROM: "AGRO-AI Academy <academy@agroai-pilot.com>" };

test("Resend: verification email is sent with the documented request shape", async () => {
  const calls = fakeInternet({ "https://api.resend.com/emails": () => json({ id: "resend-message-1" }) });
  const env = makeEnv(RESEND);
  const c = new Client(env);
  await c.get("/register");
  const r = await c.post("/register", { display_name: "Grace Wanjiru", email: "grace@academy.test", password: "terraced hillside 2026", locale: "en", accept_terms: "1" });
  assert.equal(r.status, 303);
  const send = calls.find((x) => x.url === "https://api.resend.com/emails");
  assert.ok(send, "Resend called");
  assert.equal(send.method, "POST");
  assert.equal(send.headers.authorization, `Bearer ${RESEND.RESEND_API_KEY}`);
  assert.equal(send.headers["content-type"], "application/json");
  const row = await env.DB.prepare("SELECT * FROM email_outbox WHERE to_email = 'grace@academy.test' AND template = 'verify_email'").first();
  assert.equal(send.headers["idempotency-key"], row.id, "outbox id makes retries idempotent");
  const body = JSON.parse(send.body);
  assert.equal(body.from, RESEND.EMAIL_FROM);
  assert.deepEqual(body.to, ["grace@academy.test"]);
  assert.equal(body.reply_to, "contact@agroai-pilot.com");
  assert.match(body.subject, /verify/i);
  assert.match(body.text, new RegExp(`${ORIGIN}/verify-email\\?token=[A-Za-z0-9_-]+`));
  assert.match(body.html, /href="https:\/\/academy\.test\/verify-email\?token=/);
  assert.deepEqual(body.tags, [{ name: "product", value: "academy" }, { name: "template", value: "verify_email" }]);
  assert.equal(row.status, "sent");
  assert.equal(row.provider_id, "resend-message-1");
  // The link in the delivered email verifies the account.
  const v = await c.get(new URL(/https:\/\/\S+verify-email\?token=\S+/.exec(body.text)[0]).pathname + new URL(/https:\/\/\S+verify-email\?token=\S+/.exec(body.text)[0]).search);
  assert.equal(v.status, 303);
  assert.ok((await env.DB.prepare("SELECT email_verified_at FROM users WHERE email = 'grace@academy.test'").first()).email_verified_at);
});

test("Resend: rate limits and outages are retried; rejected messages fail permanently", async () => {
  let mode = "429";
  fakeInternet({
    "https://api.resend.com/emails": () =>
      mode === "429" ? json({ name: "rate_limit_exceeded", message: "Too many requests" }, 429) : mode === "down" ? Promise.reject(new TypeError("network down")) : mode === "422" ? json({ name: "validation_error", message: "Invalid `to`" }, 422) : json({ id: "ok-1" }),
  });
  const env = makeEnv(RESEND);
  const c = new Client(env);
  await c.get("/register");
  await c.post("/register", { display_name: "Retry Test", email: "retry@academy.test", password: "terraced hillside 2026", locale: "en", accept_terms: "1" });
  let row = await env.DB.prepare("SELECT * FROM email_outbox WHERE to_email = 'retry@academy.test'").first();
  assert.equal(row.status, "pending");
  assert.equal(row.attempts, 1);
  assert.match(row.last_error, /HTTP 429/);
  mode = "down";
  await runScheduled(env, "*/15 * * * *");
  row = await env.DB.prepare("SELECT * FROM email_outbox WHERE id = ?").bind(row.id).first();
  assert.equal(row.status, "pending");
  assert.match(row.last_error, /network down/);
  mode = "ok";
  const report = await runScheduled(env, "*/15 * * * *");
  assert.equal(report.emailsSent, 1);
  assert.equal((await env.DB.prepare("SELECT status FROM email_outbox WHERE id = ?").bind(row.id).first()).status, "sent");
  // A 4xx validation error is permanent.
  mode = "422";
  const f = new Client(env);
  await f.get("/forgot-password");
  await f.post("/forgot-password", { email: "retry@academy.test" });
  const failed = await env.DB.prepare("SELECT * FROM email_outbox WHERE template = 'password_reset'").first();
  assert.equal(failed.status, "failed");
  assert.match(failed.last_error, /HTTP 422/);
});

test("Resend: password reset email link resets the password and signs out other sessions", async () => {
  const calls = fakeInternet({ "https://api.resend.com/emails": () => json({ id: "m" }) });
  const env = makeEnv(RESEND);
  const learner = await registeredLearner(env, { email: "reset@academy.test" });
  const other = new Client(env);
  await other.get("/forgot-password");
  await other.post("/forgot-password", { email: "reset@academy.test" });
  const sent = JSON.parse(calls.filter((x) => x.url.includes("resend")).pop().body);
  assert.match(sent.subject, /reset/i);
  const token = tokenFrom({ text: sent.text }, "/reset-password");
  assert.ok(token);
  await other.get(`/reset-password?token=${token}`);
  const r = await other.post("/reset-password", { token, password: "a brand new harvest passphrase" });
  assert.equal(r.status, 303);
  assert.equal((await learner.get("/dashboard")).status, 303, "existing session revoked");
  const again = new Client(env);
  await again.get("/login");
  assert.equal((await again.post("/login", { email: "reset@academy.test", password: "a brand new harvest passphrase" })).status, 303);
});

test("Resend: the certificate email links to the credential on the configured origin", async () => {
  const calls = fakeInternet({ "https://api.resend.com/emails": () => json({ id: "m" }) });
  const env = makeEnv({ ...RESEND, APP_ORIGIN: "https://academy.agroai-pilot.com" });
  await publishCourse(env, "crs_a1");
  const learner = await registeredLearner(env, { email: "certmail@academy.test" });
  const { cert } = await completeA1(env, learner);
  const mail = calls.map((x) => (x.body ? JSON.parse(x.body) : null)).find((b) => b?.tags?.some((t) => t.value === "certificate_issued"));
  assert.ok(mail, "certificate email sent");
  assert.ok(mail.text.includes(`https://academy.agroai-pilot.com/certificates/${cert.credential_id}`));
});

test("without a Resend key nothing is sent and messages are kept as unconfigured", async () => {
  const calls = fakeInternet({});
  const env = makeEnv();
  await registeredLearner(env, { email: "quiet@academy.test", verify: false });
  assert.equal(calls.length, 0);
  assert.equal((await env.DB.prepare("SELECT status FROM email_outbox WHERE to_email = 'quiet@academy.test'").first()).status, "unconfigured");
});

// ───────────── Google sign-in ─────────────

const GOOGLE = { GOOGLE_CLIENT_ID: "contract-test-client.apps.googleusercontent.com", GOOGLE_CLIENT_SECRET: "contract-test-secret-not-real" };

async function googleRoundTrip(env, client, profile, { tamperState = false } = {}) {
  let r = await client.get("/auth/google?next=/dashboard");
  assert.equal(r.status, 302);
  const auth = new URL(r.location);
  const state = auth.searchParams.get("state");
  const challenge = auth.searchParams.get("code_challenge");
  const calls = fakeInternet({
    "https://oauth2.googleapis.com/token": (req, body) => {
      const p = new URLSearchParams(body);
      const expected = createHash("sha256").update(p.get("code_verifier")).digest("base64url");
      if (expected !== challenge) return json({ error: "invalid_grant" }, 400);
      return json({ access_token: "ya29.contract-test", token_type: "Bearer", expires_in: 3599, id_token: "unused" });
    },
    "https://openidconnect.googleapis.com/v1/userinfo": (req) => (req.headers.get("authorization") === "Bearer ya29.contract-test" ? json(profile) : json({}, 401)),
  });
  r = await client.get(`/auth/google/callback?state=${tamperState ? "forged" : state}&code=4/contract-test-code`);
  return { r, auth, calls };
}

test("Google: the authorization request uses the code flow with PKCE and an exact redirect URI", async () => {
  const env = makeEnv({ ...GOOGLE, APP_ORIGIN: "https://academy.agroai-pilot.com" });
  const r = await new Client(env).get("/auth/google");
  const u = new URL(r.location);
  assert.equal(u.origin + u.pathname, "https://accounts.google.com/o/oauth2/v2/auth");
  assert.equal(u.searchParams.get("client_id"), GOOGLE.GOOGLE_CLIENT_ID);
  assert.equal(u.searchParams.get("redirect_uri"), "https://academy.agroai-pilot.com/auth/google/callback");
  assert.equal(u.searchParams.get("response_type"), "code");
  assert.equal(u.searchParams.get("scope"), "openid email profile");
  assert.equal(u.searchParams.get("code_challenge_method"), "S256");
  assert.match(u.searchParams.get("code_challenge"), /^[A-Za-z0-9_-]{43}$/);
  assert.ok(u.searchParams.get("state").length >= 24);
  const cookie = r.headers.getSetCookie().find((c) => c.includes("aca_oauth"));
  assert.match(cookie, /HttpOnly/);
  assert.match(cookie, /Secure/);
  assert.match(cookie, /SameSite=Lax/);
  assert.match(cookie, /Max-Age=600/);
});

test("Google: a verified Google account signs in, exchanging the code with the PKCE verifier", async () => {
  const env = makeEnv(GOOGLE);
  const c = new Client(env);
  const { r, calls } = await googleRoundTrip(env, c, { sub: "google-sub-1", email: "amara@gmail.test", email_verified: true, name: "Amara Okafor", locale: "fr" });
  assert.equal(r.status, 303);
  assert.equal(r.location, "/dashboard");
  const token = calls.find((x) => x.url.startsWith("https://oauth2.googleapis.com/token"));
  const p = new URLSearchParams(token.body);
  assert.equal(p.get("grant_type"), "authorization_code");
  assert.equal(p.get("client_secret"), GOOGLE.GOOGLE_CLIENT_SECRET);
  assert.equal(p.get("redirect_uri"), `${ORIGIN}/auth/google/callback`);
  const user = await env.DB.prepare("SELECT * FROM users WHERE email = 'amara@gmail.test'").first();
  assert.ok(user.email_verified_at);
  assert.equal(user.display_name, "Amara Okafor");
  assert.equal(user.locale, "fr-FR");
  assert.equal(user.password_hash, null);
  assert.equal((await c.get("/dashboard")).status, 200);
  // The next sign-in is matched by Google's subject, not by email.
  const c2 = new Client(env);
  const again = await googleRoundTrip(env, c2, { sub: "google-sub-1", email: "renamed@gmail.test", email_verified: true, name: "Amara" });
  assert.equal(again.r.status, 303);
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM users").first()).n, 1);
});

test("Google: forged state, unverified email and failed exchanges are refused", async () => {
  const env = makeEnv(GOOGLE);
  let res = await googleRoundTrip(env, new Client(env), { sub: "s", email: "x@gmail.test", email_verified: true }, { tamperState: true });
  assert.equal(res.r.status, 400);
  assert.equal(res.calls.length, 0, "no token exchange with a forged state");
  res = await googleRoundTrip(env, new Client(env), { sub: "s2", email: "y@gmail.test", email_verified: false });
  assert.equal(res.r.status, 400);
  assert.equal(await env.DB.prepare("SELECT * FROM users WHERE email = 'y@gmail.test'").first(), null);
  // A tampered PKCE verifier fails the exchange.
  const c = new Client(env);
  const r1 = await c.get("/auth/google");
  const state = new URL(r1.location).searchParams.get("state");
  const [k, v] = [...c.jar].find(([name]) => name.includes("aca_oauth"));
  c.jar.set(k, v.replace(/^([^.]+)\.[^.]+/, "$1.tampered-verifier"));
  fakeInternet({ "https://oauth2.googleapis.com/token": () => json({ error: "invalid_grant" }, 400) });
  const r2 = await c.get(`/auth/google/callback?state=${state}&code=x`);
  assert.equal(r2.status, 400);
});

test("Google: linking to an unverified password account clears that password (pre-account hijacking)", async () => {
  const env = makeEnv(GOOGLE);
  // Someone registers the address first but never verifies it.
  const squatter = await registeredLearner(env, { email: "victim@gmail.test", verify: false, password: "squatter chose this password" });
  assert.equal((await squatter.get("/dashboard")).status, 200);
  const { r } = await googleRoundTrip(env, new Client(env), { sub: "victim-sub", email: "victim@gmail.test", email_verified: true, name: "Real Owner" });
  assert.equal(r.status, 303);
  const user = await env.DB.prepare("SELECT * FROM users WHERE email = 'victim@gmail.test'").first();
  assert.equal(user.password_hash, null, "the squatter's password no longer works");
  assert.ok(user.email_verified_at);
  assert.equal((await squatter.get("/dashboard")).status, 303, "the squatter's session was revoked");
  const login = new Client(env);
  await login.get("/login");
  assert.notEqual((await login.post("/login", { email: "victim@gmail.test", password: "squatter chose this password" })).status, 303);
  assert.ok(await env.DB.prepare("SELECT 1 FROM audit_log WHERE action = 'account.unverified_password_cleared'").first());
});

test("Google sign-in is unavailable unless configured", async () => {
  const env = makeEnv();
  assert.equal((await new Client(env).get("/auth/google")).status, 404);
  assert.doesNotMatch((await new Client(env).get("/login")).text, /auth\/google/);
});

// ───────────── Certificate links ─────────────

test("certificate links use the production origin: verification URL, QR code, LinkedIn", async () => {
  const env = makeEnv({ APP_ORIGIN: "https://academy.agroai-pilot.com", LINKEDIN_ORGANIZATION_ID: "12345678" });
  await publishCourse(env, "crs_a1");
  const learner = await registeredLearner(env, { email: "links@academy.test" });
  const { cert } = await completeA1(env, learner);
  const page = await learner.get(`/certificates/${cert.credential_id}`);
  const verifyUrl = `https://academy.agroai-pilot.com/verify/${cert.credential_id}`;
  assert.ok(page.text.includes(`data-copy="${verifyUrl}"`));
  const add = new URL(/href="(https:\/\/www\.linkedin\.com\/profile\/add\?[^"]+)"/.exec(page.text)[1].replace(/&amp;/g, "&"));
  assert.equal(add.searchParams.get("certUrl"), verifyUrl);
  assert.equal(add.searchParams.get("organizationId"), "12345678");
  assert.equal(add.searchParams.get("organizationName"), null);
  const share = new URL(/href="(https:\/\/www\.linkedin\.com\/sharing\/share-offsite\/\?[^"]+)"/.exec(page.text)[1].replace(/&amp;/g, "&"));
  assert.equal(share.searchParams.get("url"), verifyUrl);
  assert.match(page.text, /rel="noopener noreferrer"/);
  const pdf = await learner.get(`/certificates/${cert.credential_id}/pdf`);
  const s = new TextDecoder("latin1").decode(new Uint8Array(await pdf.res.arrayBuffer()));
  assert.ok(s.includes(`(Verify this credential at academy.agroai-pilot.com/verify/${cert.credential_id})`));
  const pub = await new Client(env).get(`/verify/${cert.credential_id}`);
  assert.match(pub.text, new RegExp(`<link rel="canonical" href="${verifyUrl}">`));
});

// ───────────── R2 file resources ─────────────

/** In-memory R2 binding that, like R2, refuses streams of unknown length. */
function fakeR2() {
  const store = new Map();
  return {
    store,
    async put(key, value, opts) {
      if (value instanceof ReadableStream) throw new TypeError("Provided readable stream must have a known length (request/response body or readable half of FixedLengthStream)");
      const bytes = new Uint8Array(value instanceof Blob ? await value.arrayBuffer() : value);
      store.set(key, { bytes, opts });
      return { key, size: bytes.length };
    },
    async get(key) {
      const o = store.get(key);
      return o ? { body: new Blob([o.bytes]).stream(), httpMetadata: o.opts?.httpMetadata, size: o.bytes.length } : null;
    },
    async delete(key) {
      store.delete(key);
    },
  };
}

async function upload(admin, lessonId, { name, type, bytes, title }) {
  const form = new FormData();
  form.set("title", title);
  form.set("file", new File([bytes], name, { type }));
  const h = new Headers({ cookie: admin.cookieHeader(), origin: ORIGIN });
  const worker = (await import("../../src/index.js")).default;
  const res = await worker.fetch(new Request(`${ORIGIN}/admin/lessons/${lessonId}/upload?_csrf=${admin.csrf}`, { method: "POST", headers: h, body: form }), admin.env, { waitUntil() {} });
  return { status: res.status, location: res.headers.get("location") };
}

test("R2: lesson files upload, are stored with their type, and download only for enrolled learners", async () => {
  const FILES = fakeR2();
  const env = makeEnv({ FILES });
  await publishCourse(env, "crs_a1");
  const admin = await registeredLearner(env, { email: "founder@academy.test" });
  await admin.get("/admin/lessons/les_a1_data");
  const pdfBytes = new TextEncoder().encode("%PDF-1.4\n% synthetic worksheet\n");
  let r = await upload(admin, "les_a1_data", { name: "worksheet.pdf", type: "application/pdf", bytes: pdfBytes, title: "Data quality worksheet" });
  assert.match(r.location, /ok=saved/);
  // The course is released: the upload waits in the draft until the next publication.
  assert.equal(await env.DB.prepare("SELECT * FROM lesson_resources WHERE lesson_id = 'les_a1_data' AND kind = 'file'").first(), null);
  await publishDraftUnchecked(env, "crs_a1");
  const res = await env.DB.prepare("SELECT * FROM lesson_resources WHERE lesson_id = 'les_a1_data' AND kind = 'file'").first();
  assert.ok(FILES.store.has(res.file_key));
  assert.equal(FILES.store.get(res.file_key).opts.httpMetadata.contentType, "application/pdf");
  assert.equal(res.size_bytes, pdfBytes.length);

  // Content that does not match its declared type is refused.
  r = await upload(admin, "les_a1_data", { name: "x.pdf", type: "application/pdf", bytes: new TextEncoder().encode("<html><script>alert(1)</script>"), title: "Fake" });
  assert.match(decodeURIComponent(r.location), /contents do not match its type/);
  r = await upload(admin, "les_a1_data", { name: "x.txt", type: "text/plain", bytes: new TextEncoder().encode("<svg onload=alert(1)>"), title: "Fake" });
  assert.match(decodeURIComponent(r.location), /contents do not match/);
  r = await upload(admin, "les_a1_data", { name: "x.html", type: "text/html", bytes: new TextEncoder().encode("hi"), title: "Fake" });
  assert.match(decodeURIComponent(r.location), /Unsupported file type/);
  assert.equal(FILES.store.size, 1);

  // Downloads: enrolled learners only; attachment with a safe filename.
  const outsider = await registeredLearner(env, { email: "outsider@academy.test" });
  assert.equal((await outsider.get(`/resources/${res.id}`)).status, 403);
  assert.equal((await new Client(env).get(`/resources/${res.id}`)).status, 303, "sign-in required");
  const learner = await registeredLearner(env, { email: "student@academy.test" });
  await learner.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  const dl = await learner.get(`/resources/${res.id}`);
  assert.equal(dl.status, 200);
  assert.equal(dl.headers.get("content-type"), "application/pdf");
  assert.equal(dl.headers.get("content-disposition"), 'attachment; filename="Data_quality_worksheet.pdf"');
  assert.equal(dl.headers.get("x-content-type-options"), "nosniff");
  assert.equal(new TextDecoder().decode(new Uint8Array(await dl.res.arrayBuffer())), "%PDF-1.4\n% synthetic worksheet\n");
  // Withdrawing ends access to private files, even through a saved link.
  const wd = await env.DB.prepare("UPDATE enrollments SET status = 'withdrawn' WHERE user_id = (SELECT id FROM users WHERE email = 'student@academy.test')").run();
  assert.equal(wd.meta.changes, 1);
  assert.equal((await learner.get(`/resources/${res.id}`)).status, 403);
  await env.DB.prepare("UPDATE enrollments SET status = 'active' WHERE user_id = (SELECT id FROM users WHERE email = 'student@academy.test')").run();

  // Removing the resource from the draft keeps the object while the live course
  // still links it; publishing the removal deletes it.
  await admin.post(`/admin/resources/${res.id}/delete`, {});
  assert.equal(FILES.store.size, 1);
  assert.equal((await learner.get(`/resources/${res.id}`)).status, 200);
  await publishDraftUnchecked(env, "crs_a1");
  assert.equal(FILES.store.size, 0);
  assert.equal((await learner.get(`/resources/${res.id}`)).status, 404);
});

test("R2: uploads are unavailable when no bucket is bound", async () => {
  const env = makeEnv();
  const admin = await registeredLearner(env, { email: "founder@academy.test" });
  await admin.get("/admin/lessons/les_a1_data");
  const r = await upload(admin, "les_a1_data", { name: "w.pdf", type: "application/pdf", bytes: new TextEncoder().encode("%PDF-1.4"), title: "W" });
  assert.equal(r.status, 404);
});
