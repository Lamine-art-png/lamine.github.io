// Integration test for a deployed Academy over real HTTP, against its real
// Cloudflare D1 database. Run by the deploy workflow after staging deploys:
//   STAGING_TEST_INBOX_TOKEN=… node tests/remote/staging.mjs https://academy-staging.agroai-pilot.com
// Write-path checks use a synthetic @academy-staging-test.invalid learner
// (mail to it is suppressed), run only when /healthz reports "staging", and
// delete the learner at the end. The write path is mandatory: without the
// inbox token, or if any step cannot run, the test fails and production
// deployment (which needs this job) is blocked. The learner enrolls in a
// synthetic staging-only probe course, so enrollment, progress, completion,
// a certification exam, certificate issuance and verification run on every
// deploy whatever the publication state of the real courses.
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

  await step("language selection: Portuguese, French, Spanish, Arabic (right-to-left), untranslated fallback", async () => {
    // Persian has no interface catalog yet: the page is English, so it is marked and laid out as English.
    for (const [q, lang, dir] of [["pt-BR", "pt-BR", "ltr"], ["fr", "fr-FR", "ltr"], ["es", "es", "ltr"], ["ar", "ar", "rtl"], ["fa", "en", "ltr"]]) {
      const r = await new RemoteClient(BASE).get(`/courses?lang=${q}`);
      expect(r.status === 200, `/courses?lang=${q} returned ${r.status}`);
      expect(new RegExp(`<html lang="${lang}" dir="${dir}"`).test(r.text), `/courses?lang=${q} did not render lang="${lang}" dir="${dir}"`);
    }
    const fa = await new RemoteClient(BASE).get("/courses?lang=fa");
    expect(/Persian isn(?:'|&#39;)t translated yet/.test(fa.text), "untranslated language notice missing");
  });

  await step("HTTPS only, and pages sized for mobile screens", async () => {
    const r = await anon.get("/");
    expect(/<meta name="viewport" content="width=device-width/.test(r.text), "no responsive viewport");
    if (!BASE.startsWith("https://")) return "plain-HTTP harness: redirect not applicable";
    const plain = await fetch(BASE.replace(/^https:/, "http:") + "/courses?x=1", { redirect: "manual" });
    const to = plain.headers.get("location") || "";
    expect([301, 302, 307, 308].includes(plain.status) && to.startsWith(`${BASE}/courses`), `http:// returned ${plain.status} ${to}`);
    return `http → ${plain.status} https`;
  });

  await step("staging test inbox is closed without the token", async () => {
    const r = await fetch(`${BASE}/__staging/inbox?to=probe@academy-staging-test.invalid`);
    expect(r.status === 404, `inbox returned ${r.status}`);
  });

  if (environment !== "staging") throw new Error(`refusing write-path checks: target reports environment "${environment}"`);
  if (TOKEN.length < 32) {
    console.log("::error::ACADEMY_STAGING_TEST_INBOX_TOKEN is missing or shorter than 32 characters; the mandatory write-path checks cannot run.");
    throw new Error("write-path checks cannot run without the staging test inbox token (ACADEMY_STAGING_TEST_INBOX_TOKEN)");
  }

  let probe;
  await step("staging probe course is published through the revision path", async () => {
    const r = await fetch(`${BASE}/__staging/probe-course`, { method: "POST", headers: { authorization: `Bearer ${TOKEN}` } });
    expect(r.status === 200, `probe-course returned ${r.status} (is STAGING_TEST_TOKEN set on the staging Worker?)`);
    probe = (await r.json()).probe;
    expect(probe?.slug && probe.assessmentId && probe.questionId && probe.marker, "probe course details missing");
    expect(Number.isInteger(probe.revision) && probe.revision >= 1, "no revision was published");
    // A second request must publish another revision, proving the path runs every time.
    const again = await (await fetch(`${BASE}/__staging/probe-course`, { method: "POST", headers: { authorization: `Bearer ${TOKEN}` } })).json();
    expect(again.probe?.revision === probe.revision + 1, `expected revision ${probe.revision + 1}, got ${again.probe?.revision}`);
    probe = again.probe;
    return `revision ${probe.revision}`;
  });

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
    let r = await learner.get(`/verify-email?token=${tok}`);
    expect(r.status === 200, `verification page returned ${r.status}`);
    r = await learner.post("/verify-email", { token: tok });
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

  await step("enrollment, progress and lesson completion (D1 writes)", async () => {
    let r = await learner.post(`/courses/${probe.slug}/enroll`, {});
    expect(r.status === 303, `enroll returned ${r.status}`);
    r = await learner.get(`/learn/${probe.slug}`);
    expect(r.status === 302 && r.location, "resume did not redirect to a lesson");
    const lesson = await learner.get(r.location.replace(BASE, ""));
    const id = /data-lesson-id="([^"]+)"/.exec(lesson.text)?.[1];
    expect(id, "lesson id not found on the lesson page");
    expect(lesson.text.includes(probe.marker), "the newly published revision is not what learners see");
    const res = await fetch(`${BASE}/api/progress`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json", "x-csrf-token": learner.csrf, origin: BASE, cookie: [...learner.jar].map(([k, v]) => `${k}=${v}`).join("; ") },
      body: JSON.stringify({ lessonId: id, position: 0, scroll: 100, clientAt: new Date().toISOString() }),
    });
    expect(res.status === 200, `progress API returned ${res.status}`);
    r = await learner.post(`/learn/${probe.slug}/${probe.lessonSlug}/complete`, {});
    expect(r.status === 303, `lesson completion returned ${r.status}`);
  });

  let credential;
  await step("certification exam attempt, grading and certificate issuance", async () => {
    let r = await learner.post(`/assessments/${probe.assessmentId}/start`, {});
    expect(r.status === 303 && /\/attempts\//.test(r.location || ""), `exam start returned ${r.status} ${r.location || ""}`);
    const attempt = r.location.replace(BASE, "");
    await learner.get(attempt);
    r = await learner.post(`${attempt}/submit`, { [`q[${probe.questionId}]`]: probe.correctOption });
    expect(r.status === 303, `submit returned ${r.status}`);
    const page = await learner.get("/dashboard/certificates");
    credential = /href="\/certificates\/([A-Z0-9-]+)"/.exec(page.text)?.[1];
    expect(credential, "no certificate issued after passing the probe exam");
    return credential;
  });

  await step("public verification recomputes the certificate signature", async () => {
    const r = await new RemoteClient(BASE).get(`/verify/${credential}`);
    expect(r.status === 200, `verify returned ${r.status}`);
    expect(/data-verify-state="valid"/.test(r.text), "verification page does not report a valid signature");
  });

  await step("certificate PDF download and LinkedIn sharing", async () => {
    const pdf = await learner.bytes(`/certificates/${credential}/pdf`);
    expect(pdf.status === 200 && pdf.type.includes("application/pdf"), `PDF returned ${pdf.status} ${pdf.type}`);
    expect(new TextDecoder().decode(pdf.body.slice(0, 5)) === "%PDF-", "the download is not a PDF");
    const page = await learner.get(`/certificates/${credential}`);
    expect(/href="https:\/\/www\.linkedin\.com\/profile\/add\?[^"]*startTask=CERTIFICATION_NAME/.test(page.text), "no LinkedIn add-to-profile link");
    expect(page.text.includes(`/verify/${credential}`), "the share link does not point to public verification");
    return `${pdf.body.length} bytes`;
  });

  await step("administration is closed to learners", async () => {
    const r = await learner.get("/admin");
    expect(r.status === 403, `a learner opened /admin (${r.status})`);
  });

  const staff = new RemoteClient(BASE);
  const staffEmail = email.replace("staging-", "staging-staff-");
  const staffPassword = `staging staff ${Math.random().toString(36).slice(2)} passphrase`;
  await step("staff account: admin access and role restrictions", async () => {
    await staff.get("/register");
    let r = await staff.post("/register", { display_name: "Staging Test Staff", email: staffEmail, password: staffPassword, locale: "en", accept_terms: "1" });
    expect(r.status === 303, `staff register returned ${r.status}`);
    const msg = await inbox(staffEmail, "verify_email");
    const tok = tokenIn(msg.text, "/verify-email");
    await staff.get(`/verify-email?token=${tok}`);
    r = await staff.post("/verify-email", { token: tok });
    expect(r.status === 303, `staff verify returned ${r.status}`);
    const grant = await fetch(`${BASE}/__staging/staff`, { method: "POST", headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" }, body: JSON.stringify({ email: staffEmail, role: "academy_admin" }) });
    expect(grant.status === 200, `staff role grant returned ${grant.status}`);
    expect((await fetch(`${BASE}/__staging/staff`, { method: "POST", headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" }, body: JSON.stringify({ email: staffEmail, role: "super_admin" }) })).status === 400, "super_admin must never be grantable");
    r = await staff.get("/admin");
    expect(r.status === 200, `academy_admin could not open /admin (${r.status})`);
    r = await staff.get("/admin/early-access");
    expect(r.status === 403, `academy_admin opened super-admin tools (${r.status})`);
    const list = await staff.get(`/admin/learners?q=${encodeURIComponent(email)}`);
    const learnerId = /href="\/admin\/learners\/(usr_[^"]+)"/.exec(list.text)?.[1];
    if (!learnerId) {
      // Synthetic accounts only: safe to describe what the page returned.
      const table = (/<tbody>([\s\S]*?)<\/tbody>/.exec(list.text || "")?.[1] || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 300);
      throw new Error(`learner not found in the admin list (HTTP ${list.status}, page mentions the address: ${String(list.text || "").includes(email)}, rows: "${table}")`);
    }
    r = await staff.post(`/admin/learners/${learnerId}/roles`, { roles: ["academy_admin"] });
    expect(r.status === 403, `academy_admin changed roles (${r.status})`);
  });

  await step("publication requires the academic approvals (Course A1 stays unpublished)", async () => {
    const r = await staff.post("/admin/courses/crs_a1/status", { status: "published" });
    expect(r.status === 303 && /Readiness checks must pass/.test(decodeURIComponent(r.location || "")), `publishing A1 without approvals was not refused (${r.status} ${r.location || ""})`);
    const e = await learner.post(`/courses/${A1}/enroll`, {});
    expect(e.status === 303 && /error=course_not_open/.test(e.location || ""), `A1 accepted an enrollment (${e.status} ${e.location || ""})`);
  });

  await step("R2: staff upload, learner download, anonymous refusal, removal", async () => {
    const content = `Synthetic staging file ${probe.marker} ${Date.now()}`;
    let r = await staff.upload(`/admin/lessons/les_staging_probe/upload`, { title: `Staging probe file ${probe.marker}` }, { name: "probe.txt", type: "text/plain", bytes: new TextEncoder().encode(content) });
    expect(r.status === 303 && /ok=saved/.test(r.location || ""), `upload returned ${r.status} ${r.location || ""}`);
    const publish = () => fetch(`${BASE}/__staging/probe-course`, { method: "POST", headers: { authorization: `Bearer ${TOKEN}` } }).then((x) => x.json());
    await publish();
    const page = await learner.get(`/learn/${probe.slug}/${probe.lessonSlug}`);
    const id = /href="\/resources\/(res_[^"]+)"[^>]*>Staging probe file/.exec(page.text)?.[1];
    expect(id, "the uploaded file is not listed on the published lesson");
    const got = await learner.bytes(`/resources/${id}`);
    expect(got.status === 200 && new TextDecoder().decode(got.body) === content, `download returned ${got.status} with different content`);
    const anonymous = await new RemoteClient(BASE).bytes(`/resources/${id}`);
    expect(anonymous.status === 303 || anonymous.status === 401 || anonymous.status === 403, `anonymous download returned ${anonymous.status}`);
    r = await staff.post(`/admin/resources/${id}/delete`, {});
    expect(r.status === 303, `delete returned ${r.status}`);
    await publish();
    const gone = await learner.bytes(`/resources/${id}`);
    expect(gone.status === 404, `removed file still downloads (${gone.status})`);
    return `${content.length} bytes round-tripped through R2`;
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
    const v = await new RemoteClient(BASE).get(`/verify/${credential}`);
    expect(/data-verify-state="revoked"/.test(v.text), "the deleted learner's certificate is not reported as revoked");
  });

  await step("delete the synthetic staff account", async () => {
    await staff.get("/account");
    const r = await staff.post("/account/delete", { password: staffPassword, confirm: "DELETE" });
    expect(r.status === 303, `staff delete returned ${r.status}`);
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
