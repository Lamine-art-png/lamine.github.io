// Read-only deployment preflight, run by .github/workflows/academy-preflight.yml.
//   node scripts/preflight.mjs repository            secrets, Cloudflare inventory, live endpoints
//   node scripts/preflight.mjs environment <name>    secret presence inside a GitHub environment
//                                                    (academy-staging: also a read-only account inventory)
// Never creates, changes or deletes anything. Secrets are reported only as
// present/absent (from PRESENT_* variables the workflow derives); Cloudflare
// resources only by name, type and status.
import { appendFileSync } from "node:fs";

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
async function cf(path) {
  try {
    const r = await fetch(CF + path, { headers: { Authorization: `Bearer ${process.env.CLOUDFLARE_API_TOKEN}` } });
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
} else {
  console.error("usage: preflight.mjs repository | environment <name>");
  process.exit(2);
}
flush();
