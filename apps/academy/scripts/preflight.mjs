// Read-only deployment preflight, run by .github/workflows/academy-preflight.yml.
//   node scripts/preflight.mjs repository            secrets, Cloudflare inventory, live endpoints
//   node scripts/preflight.mjs environment <name>    secret presence inside a GitHub environment
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
} else {
  console.error("usage: preflight.mjs repository | environment <name>");
  process.exit(2);
}
flush();
