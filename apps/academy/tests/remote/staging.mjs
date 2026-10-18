// Integration test for a deployed Academy over real HTTP, against its real
// Cloudflare D1 database. Run by the deploy workflow after staging deploys:
//   STAGING_TEST_INBOX_TOKEN=… node tests/remote/staging.mjs https://academy-staging.agroai-pilot.com
// Write-path checks use a synthetic @academy-staging-test.invalid learner
// (mail to it is suppressed), run only when /healthz reports "staging", and
// delete the learner at the end. Without the inbox token only read-only
// checks run.
import { RemoteClient } from "./client.mjs";

const BASE = process.argv[2];
if (!BASE) {
  console.error("usage: staging.mjs <base-url>");
  process.exit(2);
}
const TOKEN = process.env.STAGING_TEST_INBOX_TOKEN || "";
const A1 = "introduction-to-ai-in-agriculture";
const results = [];
let failed = false;

async function step(name, fn) {
  const t0 = Date.now();
  try {
    const note = await fn();
    results.push(`✔ ${name}${note ? ` — ${note}` : ""} (${Date.now() - t0} ms)`);
  } catch (e) {
    failed = true;
    results.push(`✖ ${name} — ${e.message}`);
    throw e;
  }
}
const expect = (cond, msg) => {
  if (!cond) throw new Error(msg);
};

async function inbox(to, template) {
  for (let i = 0; i < 10; i++) {
    const r = await fetch(`${BASE}/__staging/inbox?to=${encodeURIComponent(to)}`, { headers: { authorization: `Bearer ${TOKEN}` } });
    if (r.ok) {
      const { message } = await r.json();
      if (message.template === template) return message;
    }
    await new Promise((res) => setTimeout(res, 1000));
  }
  throw new Error(`no ${template} message for the synthetic learner`);
}
const tokenIn = (text, path) => new RegExp(`${path}\\?token=([A-Za-z0-9_-]+)`).exec(text)?.[1];

async function main() {
  const anon = new RemoteClient(BASE);
  let environment = "";

  await step("health: database, signing and language inventory", async () => {
    const r = await anon.get("/healthz");
    expect(r.status === 200, `healthz returned ${r.status}`);
    const h = JSON.parse(r.text);
    environment = h.environment;
    expect(h.ok === true && h.database === "ok", "database not healthy");
    expect(h.certificate_signing === "configured", "certificate signing not configured");
    expect(h.courses > 0, "no courses in D1");
    expect(h.languages >= 60, "language inventory missing");
    return `environment=${h.environment}, email=${h.email}, google=${h.google_sign_in}`;
  });

  await step("security headers", async () => {
    const r = await anon.get("/");
    const required = ["content-security-policy", "x-content-type-options", "referrer-policy"];
    if (BASE.startsWith("https://")) required.push("strict-transport-security");
    for (const hdr of required) expect(r.headers.get(hdr), `missing ${hdr}`);
    expect(/frame-ancestors 'none'/.test(r.headers.get("content-security-policy")), "framing allowed");
  });

  await step("public pages read from D1", async () => {
    for (const [path, code] of [["/", 200], ["/courses", 200], [`/courses/${A1}`, 200], ["/verify", 200], ["/privacy", 200], ["/verify/AGA-0000-0000-0000", 404]]) {
      const r = await anon.get(path);
      expect(r.status === code, `${path} returned ${r.status}, expected ${code}`);
    }
  });

  await step("staging test inbox is closed without the token", async () => {
    const r = await fetch(`${BASE}/__staging/inbox?to=probe@academy-staging-test.invalid`);
    expect(r.status === 404, `inbox returned ${r.status}`);
  });

  if (environment !== "staging") throw new Error(`refusing write-path checks: target reports environment "${environment}"`);
  if (!TOKEN) {
    console.log("::warning::ACADEMY_STAGING_TEST_INBOX_TOKEN is not configured; write-path staging checks were skipped.");
    return;
  }

  const learner = new RemoteClient(BASE);
  const email = `staging-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}@academy-staging-test.invalid`;
  let password = `staging only ${Math.random().toString(36).slice(2)} passphrase`;

  await step("register a synthetic learner (D1 write)", async () => {
    await learner.get("/register");
    const r = await learner.post("/register", { display_name: "Staging Test Learner", email, password, locale: "en", accept_terms: "1" });
    expect(r.status === 303, `register returned ${r.status}`);
  });

  await step("verify email through the suppressed outbox message", async () => {
    const msg = await inbox(email, "verify_email");
    expect(msg.status === "suppressed", `test mail status ${msg.status}`);
    const tok = tokenIn(msg.text, "/verify-email");
    expect(tok, "no verification link");
    const r = await learner.get(`/verify-email?token=${tok}`);
    expect(r.status === 303, `verify returned ${r.status}`);
  });

  await step("session persists across sign-out and sign-in", async () => {
    let r = await learner.get("/dashboard");
    expect(r.status === 200 && r.text.includes("Staging Test Learner"), "dashboard did not load for the learner");
    await learner.post("/logout", {});
    r = await learner.get("/dashboard");
    expect(r.status === 303, "still signed in after sign-out");
    await learner.get("/login");
    r = await learner.post("/login", { email, password });
    expect(r.status === 303, `login returned ${r.status}`);
    r = await learner.get("/dashboard");
    expect(r.status === 200, "dashboard after sign-in");
  });

  await step("course enrollment and progress (if A1 is open on staging)", async () => {
    const page = await learner.get(`/courses/${A1}`);
    if (!page.text.includes(`/courses/${A1}/enroll`)) return "A1 is not open for enrollment on staging (upcoming); skipped";
    let r = await learner.post(`/courses/${A1}/enroll`, {});
    expect(r.status === 303, `enroll returned ${r.status}`);
    r = await learner.get(`/learn/${A1}`);
    expect(r.status === 302 && r.location, "resume did not redirect to a lesson");
    const lesson = await learner.get(r.location.replace(BASE, ""));
    const id = /data-lesson-id="([^"]+)"/.exec(lesson.text)?.[1];
    expect(id, "lesson id not found on the lesson page");
    const res = await fetch(`${BASE}/api/progress`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json", "x-csrf-token": learner.csrf, origin: BASE, cookie: [...learner.jar].map(([k, v]) => `${k}=${v}`).join("; ") },
      body: JSON.stringify({ lessonId: id, position: 17, scroll: 40, clientAt: new Date().toISOString() }),
    });
    expect(res.status === 200, `progress API returned ${res.status}`);
    return "enrolled and saved progress";
  });

  await step("password reset email and new password", async () => {
    const other = new RemoteClient(BASE);
    await other.get("/forgot-password");
    let r = await other.post("/forgot-password", { email });
    expect(r.status === 303 || r.status === 200, `forgot-password returned ${r.status}`);
    const msg = await inbox(email, "password_reset");
    const tok = tokenIn(msg.text, "/reset-password");
    expect(tok, "no reset link");
    await other.get(`/reset-password?token=${tok}`);
    password = `${password} renewed`;
    r = await other.post("/reset-password", { token: tok, password });
    expect(r.status === 303, `reset returned ${r.status}`);
    const fresh = new RemoteClient(BASE);
    await fresh.get("/login");
    r = await fresh.post("/login", { email, password });
    expect(r.status === 303, "login with the new password failed");
    Object.assign(learner, { jar: fresh.jar, csrf: fresh.csrf });
  });

  await step("delete the synthetic learner", async () => {
    await learner.get("/account");
    let r = await learner.post("/account/delete", { password, confirm: "DELETE" });
    expect(r.status === 303, `delete returned ${r.status}`);
    const again = new RemoteClient(BASE);
    await again.get("/login");
    r = await again.post("/login", { email, password });
    expect(r.status !== 303 || !(r.location || "").includes("dashboard"), "deleted account can still sign in");
  });
}

main()
  .catch((e) => {
    if (!failed) results.push(`✖ ${e.message}`);
    failed = true;
  })
  .finally(() => {
    console.log(results.join("\n"));
    console.log(failed ? "Staging integration test FAILED" : "Staging integration test passed");
    process.exit(failed ? 1 : 0);
  });
