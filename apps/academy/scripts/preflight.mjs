// Read-only deployment preflight, run by .github/workflows/academy-preflight.yml.
//   node scripts/preflight.mjs repository            secrets, Cloudflare inventory, live endpoints
//   node scripts/preflight.mjs environment <name>    secret presence inside a GitHub environment
//                                                    (academy-staging: also a read-only account inventory;
//                                                    academy-production: also credential checks)
// Never creates, changes or deletes anything. Secrets are reported only as
// present/absent (from PRESENT_* variables the workflow derives); Cloudflare
// resources only by name, type and status.
import { appendFileSync, mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { mapUploads, a1Videos } from "./stream.mjs";

const [mode, envName] = process.argv.slice(2);
const lines = [];
const out = (s = "") => {
  console.log(s);
  lines.push(s);
};
const flush = () => process.env.GITHUB_STEP_SUMMARY && appendFileSync(process.env.GITHUB_STEP_SUMMARY, lines.join("\n") + "\n");

function presence() {
  const rows = Object.entries(process.env)
    .filter(([k]) => k.startsWith("PRESENT_"))
    .map(([k, v]) => [k.slice("PRESENT_".length), v === "true"])
    .sort();
  out("| Secret | Present |");
  out("|---|---|");
  for (const [k, v] of rows) out(`| \`${k}\` | ${v ? "yes" : "**no**"} |`);
}

const CF = "https://api.cloudflare.com/client/v4";
const ACCOUNT = process.env.CLOUDFLARE_ACCOUNT_ID || "";
async function cfBase(path, token = process.env.CLOUDFLARE_API_TOKEN) {
  try {
    const r = await fetch(CF + path, { headers: { Authorization: `Bearer ${token}` } });
    const j = await r.json().catch(() => ({}));
    return { status: r.status, ok: r.ok && j.success !== false, result: j.result, errors: (j.errors || []).map((e) => e.code).join(",") };
  } catch (e) {
    return { status: 0, ok: false, result: null, errors: String(e.message).slice(0, 80) };
  }
}
async function probe(url, method = "GET") {
  try {
    const r = await fetch(url, { method, redirect: "manual", signal: AbortSignal.timeout(15000) });
    return `${r.status}${r.headers.get("location") ? ` → ${r.headers.get("location")}` : ""}`;
  } catch (e) {
    return `unreachable (${String(e.cause?.code || e.message).slice(0, 60)})`;
  }
}
const cf = (path) => cfBase(path);
const academy = (name) => /academy/i.test(String(name || ""));

async function repository() {
  out("## Repository-level secrets");
  presence();
  out("");
  await cloudflare();
}

async function cloudflare() {
  out("## Cloudflare (read-only)");
  if (!process.env.CLOUDFLARE_API_TOKEN || !ACCOUNT) {
    out("- Cloudflare token or account id is not available here; inventory skipped.");
  } else {
    let v = await cf(`/accounts/${ACCOUNT}/tokens/verify`);
    if (!v.ok) v = await cf("/user/tokens/verify");
    out(`- API token: ${v.ok ? `valid (${v.result?.status || "active"})` : `not verified (HTTP ${v.status} ${v.errors})`}`);
    const zone = await cf("/zones?name=agroai-pilot.com");
    const zoneId = zone.ok && zone.result?.[0]?.id;
    out(`- Zone agroai-pilot.com: ${zoneId ? `accessible (plan: ${zone.result[0].plan?.name || "?"})` : `not accessible (HTTP ${zone.status} ${zone.errors})`}`);
    for (const host of ["academy.agroai-pilot.com", "academy-staging.agroai-pilot.com"]) {
      if (!zoneId) break;
      const recs = await cf(`/zones/${zoneId}/dns_records?name=${host}`);
      const desc = recs.ok ? (recs.result.length ? recs.result.map((r) => `${r.type}${r.proxied ? " proxied" : ""}`).join(", ") : "none") : `unreadable (HTTP ${recs.status})`;
      out(`- DNS ${host}: ${desc}`);
    }
    const domains = await cf(`/accounts/${ACCOUNT}/workers/domains`);
    if (domains.ok) {
      const ours = domains.result.filter((d) => academy(d.hostname));
      out(`- Worker custom domains (academy): ${ours.length ? ours.map((d) => `${d.hostname} → ${d.service} (${d.environment || "production"})`).join("; ") : "none"}`);
      out(`- Worker custom domains (all, count): ${domains.result.length}`);
    } else out(`- Worker custom domains: unreadable (HTTP ${domains.status} ${domains.errors})`);
    const scripts = await cf(`/accounts/${ACCOUNT}/workers/scripts`);
    if (scripts.ok) {
      const names = scripts.result.map((s) => s.id).sort();
      out(`- Workers (${names.length}): ${names.join(", ")}`);
    } else out(`- Workers: unreadable (HTTP ${scripts.status} ${scripts.errors})`);
    const d1 = await cf(`/accounts/${ACCOUNT}/d1/database?per_page=100`);
    if (d1.ok) out(`- D1 databases (${d1.result.length}): ${d1.result.map((d) => d.name).sort().join(", ") || "none"}`);
    else out(`- D1: unreadable with this token (HTTP ${d1.status} ${d1.errors})`);
    const r2 = await cf(`/accounts/${ACCOUNT}/r2/buckets`);
    if (r2.ok) {
      const buckets = (r2.result?.buckets || r2.result || []).map((b) => b.name).sort();
      out(`- R2 buckets (${buckets.length}): ${buckets.join(", ") || "none"}`);
    } else out(`- R2: unreadable with this token (HTTP ${r2.status} ${r2.errors})`);
    await stream();
  }
}

// Read-only Cloudflare Stream inventory: titles, processing state, duration and
// protection settings. Video ids are shortened because these logs may be
// readable by others; the full mapping is written only into the private database.
const short = (uid) => `${String(uid).slice(0, 6)}…`;
async function anonymous(url) {
  if (!url) return "n/a";
  try {
    const r = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(15000) });
    return String(r.status);
  } catch (e) {
    return `unreachable (${String(e.cause?.code || e.message).slice(0, 40)})`;
  }
}
async function stream() {
  out("");
  out("## Cloudflare Stream (read-only)");
  // The Stream token (ACADEMY_STREAM_API_TOKEN) when this job has one, else the deploy token.
  const st = process.env.STREAM_API_TOKEN || process.env.CLOUDFLARE_API_TOKEN;
  out(`- Token used: ${process.env.STREAM_API_TOKEN ? "ACADEMY_STREAM_API_TOKEN" : "deploy token"}`);
  const cf = (path) => cfBase(path, st);
  const list = await cf(`/accounts/${ACCOUNT}/stream?limit=200`);
  if (!list.ok) return out(`- Stream: unreadable with this token (HTTP ${list.status} ${list.errors}) — the token needs Stream read (and, to protect videos, Stream edit)`);
  const videos = (list.result || []).sort((a, b) => String(a.meta?.name || "").localeCompare(String(b.meta?.name || "")));
  const keys = await cf(`/accounts/${ACCOUNT}/stream/keys`);
  out(`- Videos: ${videos.length}; signing keys: ${keys.ok ? (keys.result || []).length : `unreadable (HTTP ${keys.status} ${keys.errors})`}`);
  const wm = await cf(`/accounts/${ACCOUNT}/stream/watermarks`);
  out(`- Watermark profiles: ${wm.ok ? (wm.result || []).length : `unreadable (HTTP ${wm.status})`}`);
  out("");
  out("| # | Title | Id | State | Ready | Duration (s) | Signed URLs required | Allowed origins | Downloads | Captions | Anonymous HLS | Anonymous thumbnail |");
  out("|---|---|---|---|---|---|---|---|---|---|---|---|");
  let open = 0;
  for (const [i, v] of videos.entries()) {
    const dl = await cf(`/accounts/${ACCOUNT}/stream/${v.uid}/downloads`);
    const downloads = dl.ok ? Object.entries(dl.result || {}).map(([k, d]) => `${k}:${d.status}`).join(" ") || "none" : `HTTP ${dl.status}`;
    const caps = await cf(`/accounts/${ACCOUNT}/stream/${v.uid}/captions`);
    const captions = caps.ok ? (caps.result || []).map((c) => `${c.language}${c.generated ? "(auto)" : ""}:${c.status || "ready"}`).join(" ") || "none" : `HTTP ${caps.status}`;
    const hls = await anonymous(v.playback?.hls);
    const thumb = await anonymous(v.thumbnail);
    if (!v.requireSignedURLs || hls === "200") open++;
    const name = String(v.meta?.name || "(untitled)").replace(/\|/g, "/").slice(0, 80);
    out(`| ${i + 1} | ${name} | \`${short(v.uid)}\` | ${v.status?.state || "?"}${v.status?.pctComplete && v.status.state !== "ready" ? ` ${v.status.pctComplete}%` : ""} | ${v.readyToStream ? "yes" : "no"} | ${Math.round(v.duration || 0)} | ${v.requireSignedURLs ? "yes" : "**NO**"} | ${(v.allowedOrigins || []).join(" ") || "any"} | ${downloads} | ${captions} | ${hls} | ${thumb} |`);
  }
  out("");
  out(`- Videos not protected (signed URLs off, or anonymous HLS returned 200): ${open}`);
  // The mapping the protection step would apply (nothing is changed here).
  const map = mapUploads(videos.map((v) => ({ uid: v.uid, name: v.meta?.name || "" })));
  out(`- Planned A1 mapping: ${map.length} of 14 lesson videos matched`);
  out("");
  out("| Video # | Lesson | Matched upload | Id |");
  out("|---|---|---|---|");
  for (const lv of a1Videos()) {
    const m = map.find((x) => x.video.id === lv.id);
    out(`| ${lv.n} | ${lv.title} | ${m ? String(m.upload.name).replace(/\|/g, "/") : "**none**"} | ${m ? `\`${short(m.upload.uid)}\`` : ""} |`);
  }
}

// Read-only inventory of staging accounts for cleanup planning. No identifier,
// address, name or other personal field is selected, and only synthetic test
// accounts (*.invalid, filtered inside the database) are read row by row.
async function d1Query(uuid, sql, params = []) {
  try {
    const r = await fetch(`${CF}/accounts/${ACCOUNT}/d1/database/${uuid}/query`, {
      method: "POST",
      headers: { Authorization: `Bearer ${process.env.CLOUDFLARE_API_TOKEN}`, "Content-Type": "application/json" },
      body: JSON.stringify({ sql, params }),
    });
    const j = await r.json();
    return r.ok && j.success ? j.result[0].results : `HTTP ${r.status} ${(j.errors || []).map((e) => e.code).join(",")}`;
  } catch (e) {
    return String(e.message).slice(0, 80);
  }
}
async function stagingAccounts() {
  out("");
  out("## Staging accounts (read-only, no addresses)");
  const dbs = await cf(`/accounts/${ACCOUNT}/d1/database?name=agroai-academy-staging`);
  const db = dbs.ok && dbs.result?.find((d) => d.name === "agroai-academy-staging");
  if (!db) return out(`- Staging database not readable (HTTP ${dbs.status} ${dbs.errors})`);
  const totals = await d1Query(db.uuid, "SELECT COUNT(*) AS total FROM users");
  const rows = await d1Query(db.uuid, `SELECT u.status, u.created_at,
      u.email_verified_at IS NOT NULL AS verified,
      (SELECT GROUP_CONCAT(role) FROM user_roles r WHERE r.user_id = u.id) AS roles,
      (SELECT COUNT(*) FROM enrollments e WHERE e.user_id = u.id) AS enrollments,
      (SELECT COUNT(*) FROM certificates x WHERE x.user_id = u.id) AS certificates,
      (SELECT COUNT(*) FROM sessions s WHERE s.user_id = u.id) AS sessions
    FROM users u WHERE lower(u.email) LIKE '%.invalid' ORDER BY u.created_at`);
  if (!Array.isArray(rows) || !Array.isArray(totals)) return out(`- Query refused (${Array.isArray(rows) ? totals : rows})`);
  // Only synthetic accounts are read row by row, without an identifier: logs and
  // job summaries never carry a real person's account record, only a count.
  const synthetic = rows;
  const total = Number(totals[0].total);
  out(`- Accounts: ${total} total, ${synthetic.length} synthetic (*.invalid), ${total - synthetic.length} other (count only)`);
  out("");
  out("| Synthetic account | Status | Created | Verified | Roles | Enrollments | Certificates | Sessions |");
  out("|---|---|---|---|---|---|---|---|");
  synthetic.forEach((u, i) => out(`| #${i + 1} | ${u.status} | ${u.created_at} | ${u.verified ? "yes" : "no"} | ${u.roles || "-"} | ${u.enrollments} | ${u.certificates} | ${u.sessions} |`));
  const certs = await d1Query(db.uuid, "SELECT status, user_id IS NULL AS orphaned, COUNT(*) AS n FROM certificates GROUP BY 1, 2");
  if (Array.isArray(certs)) out(`- Certificates by status: ${certs.map((c) => `${c.status}${c.orphaned ? " (holder deleted)" : ""}=${c.n}`).join(", ") || "none"}`);

  // Real accounts: counts only, never a row.
  const real = await d1Query(db.uuid, `SELECT COUNT(*) AS n, COALESCE(SUM(email_verified_at IS NOT NULL), 0) AS verified,
      COALESCE(SUM(EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'super_admin')), 0) AS super_admins
    FROM users u WHERE lower(u.email) NOT LIKE '%.invalid'`);
  if (Array.isArray(real)) out(`- Real accounts: ${real[0].n}; email verified: ${real[0].verified}; super administrators: ${real[0].super_admins}`);

  // Administrator bootstrap: the configured addresses are compared inside the
  // database (as query parameters) and only counts and statuses are reported.
  const admins = String(process.env.BOOTSTRAP_ADMIN_EMAILS || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  if (!admins.length) return out("- Bootstrap administrators: none configured");
  const marks = admins.map(() => "?").join(",");
  const boot = await d1Query(db.uuid, `SELECT COUNT(*) AS registered, COALESCE(SUM(email_verified_at IS NOT NULL), 0) AS verified,
      COALESCE(SUM(EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'super_admin')), 0) AS super_admins,
      COALESCE(SUM(status = 'active'), 0) AS active
    FROM users u WHERE lower(u.email) IN (${marks})`, admins);
  const mail = await d1Query(db.uuid, `SELECT status, COUNT(*) AS n, MAX(created_at) AS latest FROM email_outbox
    WHERE template = 'verify_email' AND lower(to_email) IN (${marks}) GROUP BY status`, admins);
  if (Array.isArray(boot)) {
    const b = boot[0];
    out(`- Bootstrap administrators: ${admins.length} configured; registered: ${b.registered}; active: ${b.active}; email verified: ${b.verified}; super_admin role: ${b.super_admins}`);
  } else out(`- Bootstrap check refused (${boot})`);
  if (Array.isArray(mail)) out(`- Verification emails to those addresses: ${mail.map((m) => `${m.status}=${m.n} (latest ${m.latest})`).join(", ") || "none"}`);
  if (Array.isArray(boot) && Number(boot[0].registered) < admins.length) await bootstrapDiagnosis(db.uuid, admins);
}

// Why a configured administrator address matches no account. Only yes/no
// answers and counts are printed; addresses are compared inside the database.
async function bootstrapDiagnosis(uuid, admins) {
  const raw = String(process.env.BOOTSTRAP_ADMIN_EMAILS || "");
  out("- Bootstrap address diagnosis (no address is printed):");
  out(`  - Entries after splitting on commas: ${admins.length}`);
  const odd = [
    [/["'<>]/.test(raw), "quotes or angle brackets (paste the bare address only)"],
    [/[;\n\r]/.test(raw), "semicolons or line breaks (separate several addresses with commas)"],
    [/mailto:/i.test(raw), "a mailto: prefix"],
    [admins.some((a) => /\s/.test(a)), "a space inside an address"],
    [admins.some((a) => !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(a)), "an entry that is not an email address"],
  ].filter(([bad]) => bad);
  out(`  - Formatting problems: ${odd.length ? odd.map(([, w]) => w).join("; ") : "none"}`);
  for (const [i, a] of admins.entries()) {
    const [local, domain] = a.split("@");
    // Gmail ignores dots and anything after "+" in the local part; Google
    // accounts may also be registered under googlemail.com.
    const gmail = /^(gmail|googlemail)\.com$/.test(domain || "");
    const canon = (l) => String(l || "").split("+")[0].replace(/\./g, "");
    const r = await d1Query(uuid, `SELECT
        COALESCE(SUM(lower(email) = ?1), 0) AS exact,
        COALESCE(SUM(substr(lower(email), instr(email, '@') + 1) = ?2), 0) AS same_domain,
        COALESCE(SUM(lower(email) LIKE ?3), 0) AS same_local,
        COALESCE(SUM(?4 AND substr(lower(email), instr(email, '@') + 1) IN ('gmail.com', 'googlemail.com')
          AND replace(substr(lower(email), 1, CASE WHEN instr(email, '+') > 0 THEN instr(email, '+') - 1 ELSE instr(email, '@') - 1 END), '.', '') = ?5), 0) AS gmail_equivalent,
        COALESCE(SUM(status = 'deleted' AND lower(email) = ?1), 0) AS deleted
      FROM users`, [a, domain || "", `${local}@%`, gmail ? 1 : 0, canon(local)]);
    if (!Array.isArray(r)) {
      out(`  - Address #${i + 1}: comparison refused (${r})`);
      continue;
    }
    const x = r[0];
    out(`  - Address #${i + 1}: exact account ${x.exact > 0 ? "yes" : "no"}; an account with the same domain ${x.same_domain > 0 ? "yes" : "no"}; with the same name before @ ${x.same_local > 0 ? "yes" : "no"}; Gmail-equivalent (dots/+tag differ) ${x.gmail_equivalent > 0 ? "yes" : "no"}; deleted account ${x.deleted > 0 ? "yes" : "no"}`);
  }
}

// Production history that decides how the certificate-signing key may be set:
// a new key is safe only while no certificate exists. Counts only.
async function productionHistory() {
  out("");
  out("## Production data (read-only, counts only)");
  const dbs = await cf(`/accounts/${ACCOUNT}/d1/database?name=agroai-academy`);
  if (!dbs.ok) return out(`- D1 not readable with this environment's token (HTTP ${dbs.status} ${dbs.errors}); certificate history cannot be checked`);
  const db = (dbs.result || []).find((d) => d.name === "agroai-academy");
  if (!db) return out("- Production database `agroai-academy` does not exist yet: no accounts and no certificates have ever been issued in production");
  const n = await d1Query(db.uuid, `SELECT (SELECT COUNT(*) FROM certificates) AS certificates, (SELECT COUNT(*) FROM users) AS users`);
  if (!Array.isArray(n)) return out(`- Count refused (${n})`);
  out(`- Production database exists: ${n[0].users} account(s), ${n[0].certificates} certificate(s) ever issued`);
}

// Deployment protection of the production environment, read with the
// workflow's own token (read access). Logins of required reviewers are public.
async function protection() {
  out("");
  out("## Deployment protection: `academy-production`");
  const repo = process.env.GITHUB_REPOSITORY;
  const gh = async (path) => {
    try {
      const r = await fetch(`https://api.github.com/repos/${repo}${path}`, { headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json" } });
      return { status: r.status, body: await r.json().catch(() => ({})) };
    } catch (e) {
      return { status: 0, body: {} };
    }
  };
  if (!repo || !process.env.GITHUB_TOKEN) return out("- Not available outside GitHub Actions");
  const env = await gh("/environments/academy-production");
  if (env.status !== 200) return out(`- Environment unreadable (HTTP ${env.status})`);
  const rules = env.body.protection_rules || [];
  const reviewers = rules.find((r) => r.type === "required_reviewers");
  const people = (reviewers?.reviewers || []).map((r) => r.reviewer?.login || r.reviewer?.slug).filter(Boolean);
  const policy = env.body.deployment_branch_policy;
  let branches = "any branch";
  if (policy?.protected_branches) branches = "protected branches only";
  else if (policy?.custom_branch_policies) {
    const list = await gh("/environments/academy-production/deployment-branch-policies");
    const names = (list.body.branch_policies || []).map((b) => `${b.name}${b.type === "tag" ? " (tag)" : ""}`);
    branches = list.status === 200 ? `only: ${names.join(", ") || "none"}` : `custom (list unreadable, HTTP ${list.status})`;
  }
  const check = (ok, text) => out(`- ${ok ? "PASS" : "**FAIL**"}: ${text}`);
  check(people.length > 0, `required reviewers: ${people.length ? people.join(", ") : "none"}`);
  check(env.body.can_admins_bypass === false, `administrators can bypass: ${env.body.can_admins_bypass === false ? "no" : "yes"}`);
  check(/^only: main$/.test(branches), `deployments allowed from ${branches}`);
  const wait = rules.find((r) => r.type === "wait_timer");
  out(`- Wait timer: ${wait?.wait_timer ? `${wait.wait_timer} min` : "none"}; prevent self-review: ${reviewers?.prevent_self_review ? "yes (you cannot approve your own run)" : "no"}`);
}

// Production credential checks. Values stay in memory and are never printed:
// only pass/fail, counts and provider status codes are reported.
async function credentials() {
  out("");
  out("## Production credentials (values never printed)");
  const check = (ok, text) => out(`- ${ok ? "PASS" : "**FAIL**"}: ${text}`);
  const pass = process.env.BACKUP_PASSPHRASE || "";
  check(pass.length >= 20, "backup passphrase is at least 20 characters (the production deploy requires it)");
  if (pass) {
    const dir = mkdtempSync(join(tmpdir(), "gpg-check-"));
    try {
      writeFileSync(join(dir, "canary"), "academy backup encryption check");
      const args = ["--batch", "--yes", "--quiet", "--homedir", dir, "--pinentry-mode", "loopback", "--passphrase-fd", "0"];
      execFileSync("gpg", [...args, "--symmetric", "--cipher-algo", "AES256", "-o", join(dir, "c.gpg"), join(dir, "canary")], { input: pass, stdio: ["pipe", "ignore", "ignore"] });
      execFileSync("gpg", [...args, "-o", join(dir, "out"), "-d", join(dir, "c.gpg")], { input: pass, stdio: ["pipe", "ignore", "ignore"] });
      check(readFileSync(join(dir, "out"), "utf8") === "academy backup encryption check", "backup passphrase encrypts and decrypts with GPG AES-256");
    } catch {
      check(false, "backup passphrase encrypts and decrypts with GPG AES-256");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }
  const cert = process.env.CERT_SIGNING_SECRET || "";
  check(cert.length >= 32, "certificate signing secret is at least 32 characters (escrowed key; the deploy sets it once and never replaces it)");
  const admins = String(process.env.BOOTSTRAP_ADMIN_EMAILS || "").split(",").map((x) => x.trim()).filter(Boolean);
  const shaped = admins.filter((a) => /^[^\s@,]+@[^\s@,]+\.[a-z]{2,}$/i.test(a)).length;
  check(admins.length > 0 && shaped === admins.length, `administrator addresses: ${admins.length} configured, ${shaped} well-formed (no address printed)`);
  const key = process.env.RESEND_API_KEY || "";
  if (!key) check(false, "Resend API key present");
  else {
    try {
      const r = await fetch("https://api.resend.com/domains", { headers: { Authorization: `Bearer ${key}` }, signal: AbortSignal.timeout(15000) });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        const d = (j.data || []).find((x) => x.name === "mail.agroai-pilot.com");
        check(Boolean(d && d.status === "verified"), `Resend key valid (full access); sending domain mail.agroai-pilot.com: ${d ? d.status : "not in this Resend account"}`);
      } else if (j.name === "restricted_api_key") check(true, "Resend key valid (sending-only, as recommended; the domain list is not visible to it)");
      else check(false, `Resend key rejected (HTTP ${r.status} ${j.name || ""})`);
    } catch (e) {
      check(false, `Resend unreachable (${String(e.message).slice(0, 60)})`);
    }
  }
}

async function endpoints() {
  out("");
  out("## Live endpoints");
  for (const [label, url] of [
    ["Academy staging /healthz", "https://academy-staging.agroai-pilot.com/healthz"],
    ["Academy production /", "https://academy.agroai-pilot.com/"],
    ["Early-access form", "https://agroai-pilot.com/academy/early-access"],
    ["Company site", "https://agroai-pilot.com/"],
  ])
    out(`- ${label}: ${await probe(url)}`);
  try {
    const r = await fetch("https://api.agroai-pilot.com/v1/auth/email-delivery/status", { signal: AbortSignal.timeout(15000) });
    const j = await r.json();
    out(`- Company email delivery: HTTP ${r.status}, configured=${j.configured}, sender domain=${j.from_email_domain || "?"}, provider=${j.provider || "?"}`);
  } catch (e) {
    out(`- Company email delivery status: unreachable (${String(e.message).slice(0, 60)})`);
  }
}

if (mode === "repository") {
  await repository();
  await protection();
  await endpoints();
}
else if (mode === "environment") {
  out(`## GitHub environment \`${envName}\``);
  out("- The job started inside this environment, so it exists and this branch may use it.");
  presence();
  out("");
  out("Cloudflare access with the token this environment's deploy job receives:");
  await cloudflare();
  if (envName === "academy-staging" && process.env.CLOUDFLARE_API_TOKEN && ACCOUNT) await stagingAccounts();
  if (envName === "academy-production" && process.env.CLOUDFLARE_API_TOKEN && ACCOUNT) await productionHistory();
  if (envName === "academy-production") await credentials();
} else {
  console.error("usage: preflight.mjs repository | environment <name>");
  process.exit(2);
}
flush();
