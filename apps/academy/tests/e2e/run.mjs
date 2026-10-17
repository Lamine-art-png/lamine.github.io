// Browser end-to-end test of the critical learner journey through the real UI,
// plus mobile layout, theme, RTL and automated accessibility checks.
//
//   node tests/e2e/run.mjs [--shots <dir>]
//
// Starts the dev server on a fresh database, drives Chromium with Playwright,
// and exits non-zero on any failure. Screenshots (optional) stay local.
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "../..");
const shotsDir = process.argv.includes("--shots") ? process.argv[process.argv.indexOf("--shots") + 1] : null;
if (shotsDir) mkdirSync(shotsDir, { recursive: true });

let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch {
  ({ chromium } = await import("/opt/node-tools/node_modules/playwright/index.mjs"));
}

const port = 8900 + Math.floor(Math.random() * 90);
const base = `http://localhost:${port}`;
const dbPath = join(mkdtempSync(join(tmpdir(), "academy-e2e-")), "e2e.sqlite");
const server = spawn(process.execPath, [join(root, "dev/server.js"), "--port", String(port), "--db", dbPath], {
  env: { ...process.env, BOOTSTRAP_ADMIN_EMAILS: "founder@academy.test" },
  stdio: ["ignore", "pipe", "pipe"],
});
await new Promise((res, rej) => {
  server.stdout.on("data", (d) => String(d).includes("dev server") && res());
  server.on("exit", (c) => rej(new Error(`server exited ${c}`)));
  setTimeout(() => rej(new Error("server start timeout")), 15000);
});
const db = new DatabaseSync(dbPath);
db.exec("PRAGMA busy_timeout = 10000");
const mail = async (to, template) => {
  const r = await (await fetch(`${base}/__dev/mail`)).json();
  return r.find((m) => m.to_email === to && m.template === template);
};

const results = [];
async function step(name, fn) {
  const t0 = Date.now();
  try {
    await fn();
    results.push({ name, ok: true, ms: Date.now() - t0 });
    console.log(`✔ ${name} (${Date.now() - t0} ms)`);
  } catch (e) {
    results.push({ name, ok: false, error: e.message });
    console.log(`✖ ${name}\n  ${e.stack?.split("\n").slice(0, 4).join("\n  ")}`);
  }
}
const shot = async (page, name) => shotsDir && page.screenshot({ path: join(shotsDir, `${name}.png`), fullPage: true });

/** Automated checks: labels, alt text, landmarks, headings, WCAG contrast, overflow. */
async function a11y(page, label) {
  const problems = await page.evaluate(() => {
    const out = [];
    const lum = (c) => {
      const [r, g, b] = c.map((v) => {
        v /= 255;
        return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    // Handles rgb()/rgba() and color(srgb r g b / a) produced by color-mix().
    const parse = (s) => {
      const n = (s.match(/[\d.]+/g) || []).map(Number);
      return s.startsWith("color(") ? [n[0] * 255, n[1] * 255, n[2] * 255, n[3] ?? 1] : n;
    };
    const bgOf = (el) => {
      for (let e = el; e; e = e.parentElement) {
        const cs = getComputedStyle(e);
        if (cs.backgroundImage !== "none" && !/gradient/.test(cs.backgroundImage)) return null;
        const [r, g, b, a = 1] = parse(cs.backgroundColor);
        if (a > 0.9) return [r, g, b];
        if (/gradient/.test(cs.backgroundImage)) return null;
      }
      return [255, 255, 255];
    };
    if (!document.querySelector("main")) out.push("no <main> landmark");
    if (document.querySelectorAll("h1").length !== 1) out.push(`expected one h1, found ${document.querySelectorAll("h1").length}`);
    for (const img of document.querySelectorAll("img")) if (!img.hasAttribute("alt")) out.push(`img without alt: ${img.src}`);
    for (const el of document.querySelectorAll("input:not([type=hidden]), select, textarea")) {
      const id = el.id;
      const labelled = el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") || (id && document.querySelector(`label[for="${id}"]`)) || el.closest("label");
      if (!labelled && el.closest("[aria-hidden=true]") == null) out.push(`unlabelled control: ${el.name || el.outerHTML.slice(0, 60)}`);
    }
    for (const a of document.querySelectorAll("a, button")) {
      if (!a.textContent.trim() && !a.getAttribute("aria-label") && !a.querySelector("img[alt]:not([alt=''])") && !a.title && a.offsetParent) out.push(`empty link/button: ${a.outerHTML.slice(0, 80)}`);
    }
    const seen = new Set();
    for (const el of document.querySelectorAll("body *")) {
      if (!el.offsetParent || el.closest("svg, .certificate, [hidden], .hero-visual img")) continue;
      const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
      if (!own) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || Number(cs.opacity) < 0.5) continue;
      const bg = bgOf(el);
      if (!bg) continue;
      const fg = parse(cs.color);
      const L1 = lum(fg.slice(0, 3));
      const L2 = lum(bg);
      const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
      const size = parseFloat(cs.fontSize);
      const large = size >= 24 || (size >= 18.66 && Number(cs.fontWeight) >= 700);
      const disabled = el.closest("[disabled], [aria-disabled=true]");
      if (!disabled && ratio < (large ? 3 : 4.5)) {
        const key = `${el.tagName}.${el.className}`;
        if (!seen.has(key)) {
          seen.add(key);
          out.push(`contrast ${ratio.toFixed(2)} for "${el.textContent.trim().slice(0, 40)}" (${key})`);
        }
      }
    }
    for (const el of document.querySelectorAll("header *, main *")) {
      if (!el.offsetParent || el.closest("[hidden], .sr-only, .skip-link, .table-wrap, .admin-table, details:not([open]) > :not(summary)")) continue;
      const r = el.getBoundingClientRect();
      if (r.width && (r.left < -1 || r.right > window.innerWidth + 1)) {
        out.push(`element outside viewport: <${el.tagName.toLowerCase()} class="${el.className}"> ${Math.round(r.left)}..${Math.round(r.right)}`);
        break;
      }
    }
    if (document.documentElement.scrollWidth > window.innerWidth + 1) out.push(`horizontal overflow: ${document.documentElement.scrollWidth}px > ${window.innerWidth}px`);
    return out;
  });
  if (problems.length) throw new Error(`${label}: accessibility problems:\n  - ${problems.join("\n  - ")}`);
}

const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("pageerror", (e) => consoleErrors.push(e.message));
  page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && consoleErrors.push(m.text()));

  await step("public pages render accessibly", async () => {
    for (const [path, name] of [["/", "home"], ["/courses", "catalog"], ["/courses/introduction-to-ai-in-agriculture", "course"], ["/programs", "programs"], ["/paths", "paths"], ["/verify", "verify-form"], ["/faq", "faq"], ["/about", "about"], ["/contact", "contact"], ["/privacy", "privacy"], ["/register", "register"], ["/login", "login"]]) {
      await page.goto(base + path);
      await a11y(page, path);
      await shot(page, `public-${name}`);
    }
  });

  await step("founder registers, verifies and publishes Course A1 from the admin console", async () => {
    await page.goto(`${base}/register`);
    await page.fill("#f-display_name", "Academy Founder");
    await page.fill("#f-email", "founder@academy.test");
    await page.fill("#f-password", "harvest moon over the valley");
    await page.check('input[name="accept_terms"]');
    await page.click('button[type="submit"]:has-text("Create free account")');
    await page.waitForURL(/\/dashboard\?welcome=1/);
    const m = await mail("founder@academy.test", "verify_email");
    await page.goto(/https?:\/\/\S+verify-email\?token=\S+/.exec(m.text)[0]);
    await page.goto(`${base}/admin/courses/crs_a1`);
    await shot(page, "admin-course");
    assert.equal(await page.locator("text=❌").count(), 0, "readiness checks pass");
    await page.selectOption("#st", "published");
    await page.click('button:has-text("Apply")');
    await page.waitForSelector("text=Course published.");
    await page.goto(`${base}/admin`);
    await a11y(page, "/admin");
    await shot(page, "admin-analytics");
    await page.click('summary.avatar-btn');
    await page.click('button:has-text("Sign out")');
  });

  const learner = await browser.newContext({ viewport: { width: 1280, height: 860 }, locale: "en-US" });
  const lp = await learner.newPage();
  lp.on("pageerror", (e) => consoleErrors.push(e.message));

  await step("learner registers and verifies email", async () => {
    await lp.goto(`${base}/courses/introduction-to-ai-in-agriculture`);
    await lp.click('a:has-text("Enroll for free")');
    await lp.fill("#f-display_name", "Amina Diallo");
    await lp.fill("#f-email", "amina@academy.test");
    await lp.fill("#f-password", "millet and sorghum 2026");
    await lp.selectOption("#f-professional_role", "student");
    await lp.selectOption("#f-country", "SN");
    await lp.check('input[name="accept_terms"]');
    await lp.click('button:has-text("Create free account")');
    await lp.waitForURL(/\/courses\/introduction-to-ai-in-agriculture/);
    const m = await mail("amina@academy.test", "verify_email");
    await lp.goto(/https?:\/\/\S+verify-email\?token=\S+/.exec(m.text)[0]);
    await lp.waitForURL(/verified=1/);
  });

  await step("learner enrolls and studies with saved progress", async () => {
    await lp.goto(`${base}/courses/introduction-to-ai-in-agriculture`);
    await lp.click('button:has-text("Enroll for free")');
    await lp.waitForURL(/\/learn\/introduction-to-ai-in-agriculture\/welcome/);
    await a11y(lp, "lesson");
    await shot(lp, "lesson");
    // Notes save without a reload.
    await lp.fill("#note-body", "Ask the co-op about soil probes.");
    await lp.click('button:has-text("Save note")');
    await lp.waitForSelector("text=Ask the co-op about soil probes.");
    const lessons = db.prepare("SELECT slug, type FROM lessons WHERE course_id='crs_a1' ORDER BY sort_order").all();
    for (const l of lessons.filter((x) => x.type !== "quiz")) {
      await lp.goto(`${base}/learn/introduction-to-ai-in-agriculture/${l.slug}`);
      await lp.click('button:has-text("Mark as complete")');
      await lp.waitForLoadState();
    }
    const enr = db.prepare("SELECT progress_pct FROM enrollments e JOIN users u ON u.id = e.user_id WHERE u.email='amina@academy.test'").get();
    assert.ok(enr.progress_pct > 50, `progress ${enr.progress_pct}%`);
  });

  async function answerAll(page, attemptId) {
    const layout = JSON.parse(db.prepare("SELECT layout_json FROM attempts WHERE id = ?").get(attemptId).layout_json);
    for (const { q: qid } of layout) {
      const q = db.prepare("SELECT type, answer_json FROM questions WHERE id = ?").get(qid);
      const key = JSON.parse(q.answer_json);
      const fs = `#q-${qid}`;
      if (q.type === "single") await page.check(`${fs} input[value="${key.correct[0]}"]`);
      if (q.type === "multiple") for (const id of key.correct) await page.check(`${fs} input[value="${id}"]`);
      if (q.type === "true_false") await page.check(`${fs} input[value="${key.value}"]`);
      if (q.type === "short_answer") await page.fill(`${fs} textarea`, key.accepted[0]);
      if (q.type === "matching") for (const [l, r] of Object.entries(key.pairs)) await page.selectOption(`#m-${qid}-${l}`, r);
      if (q.type === "ordering") for (const [i, id] of key.order.entries()) await page.selectOption(`#o-${qid}-${id}`, String(i + 1));
    }
  }

  await step("learner takes the module quizzes in the exam interface", async () => {
    for (const quiz of ["asm_a1_q1", "asm_a1_q2", "asm_a1_q3"]) {
      await lp.goto(`${base}/assessments/${quiz}`);
      await lp.click('button:has-text("Begin")');
      await lp.waitForURL(/\/attempts\//);
      const attemptId = lp.url().split("/").pop();
      await answerAll(lp, attemptId);
      lp.once("dialog", (d) => d.accept());
      await lp.click('button:has-text("Submit answers")');
      await lp.waitForSelector("text=You passed!");
      if (quiz === "asm_a1_q1") {
        await a11y(lp, "quiz results");
        await shot(lp, "quiz-results");
      }
    }
  });

  await step("final exam: timer, autosave, submission, certificate", async () => {
    await lp.goto(`${base}/assessments/asm_a1_exam`);
    await shot(lp, "exam-intro");
    await lp.click('button:has-text("Begin")');
    await lp.waitForURL(/\/attempts\//);
    const attemptId = lp.url().split("/").pop();
    await lp.locator("[data-timer-text]").filter({ hasText: /\d+:\d\d/ }).waitFor();
    await a11y(lp, "exam");
    await answerAll(lp, attemptId);
    // Autosave persists answers server-side before submission.
    await lp.locator("[data-save-state]").filter({ hasText: "✓" }).waitFor({ timeout: 15000 });
    const saved = db.prepare("SELECT COUNT(*) AS n FROM attempt_answers WHERE attempt_id = ? AND response_json IS NOT NULL").get(attemptId).n;
    assert.ok(saved >= 15, `autosaved ${saved} answers`);
    await shot(lp, "exam");
    lp.once("dialog", (d) => d.accept());
    await lp.click('button:has-text("Submit answers")');
    await lp.waitForURL(/\/certificates\/AGA-/);
    await a11y(lp, "certificate");
    await shot(lp, "certificate");
  });

  let credential;
  await step("certificate: PDF download, LinkedIn and public verification", async () => {
    credential = lp.url().match(/AGA-[0-9A-Z-]+/)[0];
    const [download] = await Promise.all([lp.waitForEvent("download"), lp.click('a:has-text("Download PDF")')]);
    const path = await download.path();
    const bytes = await import("node:fs").then((fs) => fs.readFileSync(path));
    assert.equal(bytes.subarray(0, 8).toString(), "%PDF-1.4");
    if (shotsDir) writeFileSync(join(shotsDir, "certificate.pdf"), bytes);
    const li = await lp.getAttribute('a:has-text("Add to LinkedIn profile")', "href");
    const u = new URL(li);
    assert.equal(u.hostname, "www.linkedin.com");
    assert.equal(u.searchParams.get("certId"), credential);
    const pub = await browser.newPage();
    await pub.goto(`${base}/verify`);
    await pub.fill("#cred", credential.toLowerCase());
    await pub.click('button:has-text("Verify")');
    await pub.waitForSelector("text=Valid credential");
    await a11y(pub, "verify result");
    await shot(pub, "verify-result");
    await pub.close();
  });

  await step("dashboard reflects real progress, results and credentials", async () => {
    await lp.goto(`${base}/dashboard`);
    await lp.waitForSelector(".kpi");
    const kpis = await lp.$$eval(".kpi .value", (els) => els.map((e) => e.textContent.trim()));
    assert.equal(kpis[1], "1", "one completed course");
    assert.equal(kpis[3], "1", "one certificate");
    await a11y(lp, "dashboard");
    await shot(lp, "dashboard");
    await lp.goto(`${base}/dashboard/certificates`);
    await lp.waitForSelector(`text=${credential}`);
  });

  await step("mobile layout, dark theme and RTL", async () => {
    const mobile = await browser.newContext({ viewport: { width: 375, height: 780 }, isMobile: true, hasTouch: true, colorScheme: "dark" });
    const mp = await mobile.newPage();
    for (const path of ["/", "/courses", "/courses/introduction-to-ai-in-agriculture", "/verify/" + credential, "/register"]) {
      await mp.goto(base + path);
      await a11y(mp, `mobile dark ${path}`);
    }
    await shot(mp, "mobile-dark-register");
    await mp.goto(`${base}/?lang=ar`);
    assert.equal(await mp.getAttribute("html", "dir"), "rtl");
    await a11y(mp, "mobile rtl home");
    await shot(mp, "mobile-rtl-home");
    await mp.click("summary.icon-btn");
    await mobile.close();
  });

  await step("no client-side errors", async () => {
    assert.deepEqual(consoleErrors, []);
  });
} finally {
  await browser.close();
  server.kill();
}

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} end-to-end steps passed`);
process.exit(failed.length ? 1 : 0);
