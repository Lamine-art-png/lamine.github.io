// Automated WCAG 2.2 A/AA scan with axe-core over public, learner and admin
// pages (light and dark, LTR and RTL). Fails on serious or critical
// violations; lists the rest. Needs `axe-core` installed (CI installs it).
//   node tests/e2e/axe.mjs
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { DatabaseSync } from "node:sqlite";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
let axeSource;
try {
  axeSource = readFileSync(createRequire(join(root, "package.json")).resolve("axe-core/axe.min.js"), "utf8");
} catch {
  console.log("axe-core is not installed; skipping the axe scan (CI installs it).");
  process.exit(0);
}
let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch {
  ({ chromium } = await import("/opt/node-tools/node_modules/playwright/index.mjs"));
}

const port = 8800 + Math.floor(Math.random() * 90);
const base = `http://localhost:${port}`;
const dbPath = join(mkdtempSync(join(tmpdir(), "academy-axe-")), "axe.sqlite");
const server = spawn(process.execPath, [join(root, "dev/server.js"), "--port", String(port), "--db", dbPath], {
  env: { ...process.env, BOOTSTRAP_ADMIN_EMAILS: "founder@academy.test" },
  stdio: ["ignore", "pipe", "pipe"],
});
await new Promise((res, rej) => {
  server.stdout.on("data", (d) => String(d).includes("dev server") && res());
  setTimeout(() => rej(new Error("server start timeout")), 15000);
});
const db = new DatabaseSync(dbPath);
db.exec("PRAGMA busy_timeout = 10000");
db.prepare("UPDATE courses SET status = 'published', published_at = ? WHERE id = 'crs_a1'").run(new Date().toISOString());
const mail = async (to) => (await (await fetch(`${base}/__dev/mail`)).json()).find((m) => m.to_email === to && m.template === "verify_email");

const browser = await chromium.launch();
// axe is injected as a script, so this context bypasses the site's CSP (scan only).
const ctx = await browser.newContext({ bypassCSP: true, viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();

async function signUp(email, name) {
  await page.goto(`${base}/register?lang=en`);
  await page.fill("#f-display_name", name);
  await page.fill("#f-email", email);
  await page.fill("#f-password", "a long synthetic passphrase 2026");
  await page.check('input[name="accept_terms"]');
  await page.click('button:has-text("Create free account")');
  await page.waitForURL(/dashboard/);
  const m = await mail(email);
  await page.goto(/https?:\/\/\S+verify-email\?token=\S+/.exec(m.text)[0]);
}

const results = [];
async function scan(path, { label = path, theme = null } = {}) {
  if (theme) await ctx.addCookies([{ name: "aca_theme", value: theme, url: base }]);
  const res = await page.goto(base + path);
  if (!res || res.status() >= 400) throw new Error(`${label}: HTTP ${res?.status()} (scan only real pages)`);
  await page.evaluate(axeSource);
  const r = await page.evaluate(async () => {
    const out = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] }, resultTypes: ["violations"] });
    return out.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.slice(0, 3).map((n) => n.target.join(" ")) }));
  });
  results.push({ label, violations: r });
  if (theme) await ctx.clearCookies({ name: "aca_theme" });
}

try {
  for (const p of ["/", "/courses", "/courses/introduction-to-ai-in-agriculture", "/programs", "/paths", "/languages", "/verify", "/faq", "/about", "/help", "/contact", "/accessibility", "/privacy", "/terms", "/register", "/login", "/forgot-password"]) await scan(p);
  await scan("/?lang=ar", { label: "/ (Arabic, RTL)" });
  await scan("/courses?lang=es", { label: "/courses (Spanish, machine translation notice)" });
  await scan("/", { label: "/ (dark)", theme: "dark" });
  await page.goto(`${base}/?lang=en`);

  await signUp("learner@academy.test", "Synthetic Learner");
  await page.goto(`${base}/courses/introduction-to-ai-in-agriculture`);
  await page.click('button:has-text("Enroll for free")');
  await page.waitForURL(/\/learn\//);
  for (const p of ["/dashboard", "/dashboard/certificates", "/learn/introduction-to-ai-in-agriculture/welcome", "/learn/introduction-to-ai-in-agriculture/what-ai-is", "/assessments/asm_a1_q1", "/account"]) await scan(p);
  await scan("/learn/introduction-to-ai-in-agriculture/welcome", { label: "lesson (dark)", theme: "dark" });
  await page.goto(`${base}/assessments/asm_a1_q1`);
  await page.click('button:has-text("Begin")');
  await page.waitForURL(/\/attempts\//);
  await scan(new URL(page.url()).pathname, { label: "quiz attempt" });

  await ctx.clearCookies();
  await signUp("founder@academy.test", "Synthetic Founder");
  for (const p of ["/admin", "/admin/courses", "/admin/courses/crs_a1", "/admin/lessons/les_a1_data", "/admin/videos", "/admin/assessments/asm_a1_exam", "/admin/learners", "/admin/certificates", "/admin/translations", "/admin/audit"]) await scan(p);
} finally {
  await browser.close();
  server.kill();
}

let blocking = 0;
for (const r of results) {
  const serious = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  blocking += serious.length;
  const mark = serious.length ? "✖" : r.violations.length ? "•" : "✔";
  console.log(`${mark} ${r.label}${r.violations.length ? "" : " — no violations"}`);
  for (const v of r.violations) console.log(`    [${v.impact}] ${v.id}: ${v.help} — ${v.nodes.join(" | ")}`);
}
console.log(`\naxe: ${results.length} pages scanned, ${blocking} serious/critical violation type(s)`);
process.exit(blocking ? 1 : 0);
