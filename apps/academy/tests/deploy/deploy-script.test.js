// Runs scripts/deploy.sh against a fake wrangler and a fake Cloudflare API to
// prove its safety rules: environment separation, verified durable backups
// before migrations, and certificate-key protection.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { mkdtempSync, mkdirSync, cpSync, readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";
import { DatabaseSync } from "node:sqlite";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const FAKE = join(root, "tests/deploy/fake-wrangler.mjs");

/**
 * Fake Cloudflare API: the zone exists; `foreignHost` has an unrelated DNS record.
 * With `dnsForbidden` the token cannot read DNS records (HTTP 403) and the
 * public resolver (`/dns-query`) answers instead, listing `publicHosts`.
 */
async function cloudflareApi({ foreignHost = null, ownedHosts = [], dnsForbidden = false, publicHosts = [] } = {}) {
  const server = createServer((req, res) => {
    const u = new URL(req.url, "http://x");
    let body = { success: true, result: [] };
    if (u.pathname.endsWith("/dns-query")) {
      const name = u.searchParams.get("name");
      res.writeHead(200, { "content-type": "application/dns-json" });
      return res.end(JSON.stringify({ Status: 0, Answer: publicHosts.includes(name) && u.searchParams.get("type") === "A" ? [{ name, type: 1, data: "192.0.2.1" }] : undefined }));
    }
    if (dnsForbidden && u.pathname.includes("/dns_records")) {
      res.writeHead(403, { "content-type": "application/json" });
      return res.end(JSON.stringify({ success: false, errors: [{ code: 10000, message: "Authentication error" }] }));
    }
    if (u.pathname.endsWith("/zones")) body.result = [{ id: "zone123", name: "agroai-pilot.com" }];
    // Stream: an account without uploads; a signing key can be created.
    else if (u.pathname.endsWith("/stream/keys")) body.result = { id: "kid-test", jwk: Buffer.from("{}").toString("base64") };
    else if (u.pathname.includes("/dns_records")) {
      const name = u.searchParams.get("name");
      if (name === foreignHost || ownedHosts.some((h) => h.host === name)) body.result = [{ id: "rec1", name, type: "CNAME" }];
    } else if (u.pathname.endsWith("/workers/domains")) {
      body.result = ownedHosts.filter((h) => h.host === u.searchParams.get("hostname")).map((h) => ({ hostname: h.host, service: h.service }));
    }
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify(body));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const origin = `http://127.0.0.1:${server.address().port}`;
  return { base: `${origin}/client/v4`, doh: `${origin}/dns-query`, close: () => server.close() };
}

function workspace() {
  const dir = mkdtempSync(join(tmpdir(), "academy-deploy-"));
  cpSync(join(root, "wrangler.toml"), join(dir, "wrangler.toml"));
  cpSync(join(root, "migrations"), join(dir, "migrations"), { recursive: true });
  const state = join(dir, ".fake");
  mkdirSync(state);
  return { dir, state };
}

function run(ws, target, api, extraEnv = {}) {
  return new Promise((resolve) => {
    const child = spawn("bash", [join(root, "scripts/deploy.sh"), target], {
      cwd: ws.dir,
      env: {
        PATH: process.env.PATH,
        HOME: ws.dir,
        ACADEMY_WRANGLER: `node ${FAKE}`,
        CF_API_BASE: api.base,
        DOH_BASE: api.doh,
        FAKE_STATE: ws.state,
        CLOUDFLARE_API_TOKEN: "test-token-not-real",
        CLOUDFLARE_ACCOUNT_ID: "acct-test",
        STREAM_API_TOKEN: "test-stream-token-not-real",
        GITHUB_SHA: "abc1234",
        ...extraEnv,
      },
    });
    let out = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (out += d));
    child.on("close", (code) => resolve({ code, out, calls: existsSync(join(ws.state, "calls.log")) ? readFileSync(join(ws.state, "calls.log"), "utf8") : "" }));
  });
}

const json = (ws, f) => JSON.parse(readFileSync(join(ws.state, f), "utf8"));
const PASS = "synthetic test passphrase";
const prod = { ACADEMY_DEPLOY_CONFIRM: "production", BACKUP_PASSPHRASE: PASS, CERT_SIGNING_SECRET: "c".repeat(64) };
const gpgDecrypt = (ws, file) => execFileSync("gpg", ["--batch", "--quiet", "--pinentry-mode", "loopback", "--passphrase", PASS, "--homedir", ws.dir, "-d", file]);

/** Production with learner data and an existing signing key. */
async function liveProduction(api) {
  const ws = workspace();
  const first = await run(ws, "production", api, { ...prod, BOOTSTRAP_ADMIN_EMAILS: "founder@academy.test" });
  assert.equal(first.code, 0, first.out);
  const db = new DatabaseSync(join(ws.state, "d1-agroai-academy.sqlite"));
  const now = new Date().toISOString();
  db.prepare("INSERT INTO users (id, email, display_name, created_at, updated_at) VALUES ('usr_1', 'grower@academy.test', 'Synthetic Grower', ?, ?)").run(now, now);
  db.prepare(
    "INSERT INTO certificates (id, credential_id, user_id, course_id, credential_name, course_title, issued_at, status, signature, created_at) VALUES ('crt_1','AGA-AAAA-BBBB-CCCC','usr_1','crs_a1','Synthetic Grower','Intro',?, 'active', ?, ?)",
  ).run(now, "0".repeat(64), now);
  db.prepare("INSERT INTO users (id, email, display_name, created_at, updated_at) VALUES ('usr_2', 'other@academy.test', 'Synthetic Other', ?, ?)").run(now, now);
  db.prepare("INSERT INTO enrollments (id, user_id, course_id, enrolled_at, last_activity_at) VALUES ('enr_1', 'usr_1', 'crs_a1', ?, ?)").run(now, now);
  db.prepare("INSERT INTO attempts (id, user_id, assessment_id, course_id, attempt_no, status, layout_json, started_at, policy_json) VALUES ('att_1', 'usr_1', 'asm_a1_exam', 'crs_a1', 1, 'in_progress', '[]', ?, ?)").run(now, JSON.stringify({ passing_score: 80 }));
  db.close();
  writeFileSync(join(ws.state, "calls.log"), "");
  return ws;
}

test("no deployment starts without the Stream token that verifies video protection", async () => {
  const api = await cloudflareApi();
  for (const target of ["staging", "production"]) {
    const ws = workspace();
    const r = await run(ws, target, api, { ...prod, STREAM_API_TOKEN: "" });
    assert.notEqual(r.code, 0, target);
    assert.match(r.out, /STREAM_API_TOKEN is required/);
    assert.doesNotMatch(r.calls, /deploy|migrations apply|d1 export/, `${target}: nothing changed`);
  }
  api.close();
});

test("production refuses to deploy without explicit confirmation", async () => {
  const api = await cloudflareApi();
  const ws = workspace();
  const r = await run(ws, "production", api);
  api.close();
  assert.equal(r.code, 2);
  assert.match(r.out, /ACADEMY_DEPLOY_CONFIRM=production/);
  assert.equal(r.calls, "", "no Cloudflare command ran");
});

test("a fresh staging deploy touches only staging resources", async () => {
  const api = await cloudflareApi();
  const ws = workspace();
  const r = await run(ws, "staging", api, { BOOTSTRAP_ADMIN_EMAILS: "founder@academy.test", RESEND_API_KEY: "re_test_not_real" });
  api.close();
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /New or empty database: nothing to back up/);
  const dbs = json(ws, "d1.json").map((d) => d.name);
  assert.deepEqual(dbs, ["agroai-academy-staging"]);
  const deployed = json(ws, "deployed-staging.json").config;
  const stagingId = json(ws, "d1.json")[0].uuid;
  assert.match(deployed, new RegExp(`database_name = "agroai-academy-staging"\\ndatabase_id = "${stagingId}"`));
  assert.match(deployed, /database_name = "agroai-academy"\ndatabase_id = "00000000-0000-0000-0000-000000000000"/, "production database id untouched");
  assert.ok(!existsSync(join(ws.state, "deployed-production.json")));
  const secrets = json(ws, "secrets-staging.json");
  assert.equal(secrets.CERT_SIGNING_SECRET.length, 64, "strong signing key generated");
  assert.ok(secrets.BOOTSTRAP_ADMIN_EMAILS && secrets.RESEND_API_KEY);
  assert.ok(!existsSync(join(ws.state, "secrets-production.json")), "no production secret written");
  assert.deepEqual(json(ws, "buckets.json"), ["agroai-academy-staging-files"], "only the staging file bucket");
  assert.match(deployed, /bucket_name = "agroai-academy-staging-files"/);
  assert.match(r.calls, /migrations apply agroai-academy-staging --remote --config wrangler.generated.toml --env staging/);
  assert.match(r.out, /Caption mode: read-only \(staging\)/, "staging never writes the shared caption tracks");
  assert.doesNotMatch(r.out, /test-token-not-real|re_test_not_real/, "secrets never printed");
  assert.ok(!existsSync(join(ws.dir, "wrangler.generated.toml")), "generated config removed");
});

test("existing production data is exported, verified and stored before migrations", async () => {
  const api = await cloudflareApi({ ownedHosts: [{ host: "academy.agroai-pilot.com", service: "agroai-academy" }] });
  const ws = await liveProduction(api);
  const before = json(ws, "secrets-production.json").CERT_SIGNING_SECRET.sha256;
  const r = await run(ws, "production", api, prod);
  api.close();
  assert.equal(r.code, 0, r.out);
  const calls = r.calls.split("\n");
  const idx = (re) => calls.findIndex((l) => re.test(l));
  assert.ok(idx(/^d1 export/) >= 0 && idx(/^r2 object put/) > idx(/^d1 export/) && idx(/^r2 object get/) > idx(/^r2 object put/), "export → upload → read-back");
  assert.ok(idx(/^d1 migrations apply/) > idx(/^r2 object get/), "migrations only after the backup is confirmed");
  assert.ok(idx(/^deploy/) > idx(/^d1 migrations apply/));
  assert.match(r.out, /Restore check passed/);
  assert.match(r.out, /Time Travel bookmark: 00000085/);
  assert.match(r.out, /Caption mode: writer \(production\)/, "production is the caption writer");
  const dir = join(ws.state, "r2", "agroai-academy-backups", "d1", "agroai-academy");
  const [file] = readdirSync(dir);
  assert.match(file, /^\d{8}T\d{6}Z-abc1234\.sql\.gz\.gpg$/);
  assert.throws(() => gunzipSync(readFileSync(join(dir, file))), "stored object is not a readable export");
  assert.match(r.out, /Encrypted backup decrypted from the stored copy and matches the verified export/);
  const sql = gunzipSync(gpgDecrypt(ws, join(dir, file))).toString("utf8");
  assert.match(sql, /INSERT INTO "users".*grower@academy\.test/);
  assert.match(sql, /AGA-AAAA-BBBB-CCCC/);
  assert.equal(json(ws, "secrets-production.json").CERT_SIGNING_SECRET.sha256, before, "existing signing key never replaced");
  assert.match(r.out, /CERT_SIGNING_SECRET already present; left unchanged/);
});

for (const [failure, message] of [
  ["export", /Database export failed; refusing to migrate/],
  ["truncated-export", /Backup verification failed/],
  ["lossy-export", /Backup verification failed.*users/],
  ["drop-one-certificate", /Backup verification failed.*table certificates: 1 record\(s\) missing/],
  ["drop-one-attempt", /Backup verification failed.*table attempts: 1 record\(s\) missing/],
  ["drop-one-enrollment", /Backup verification failed.*table enrollments: 1 record\(s\) missing/],
  ["alter-certificate", /Backup verification failed.*table certificates: 1 record\(s\) differ/],
  ["strip-attempt-snapshot", /Backup verification failed.*table attempts: 1 record\(s\) differ/],
  ["certificate-vanishes", /Backup verification failed.*certificates: 1 append-only record\(s\) disappeared/],
  ["put", /Backup upload failed; refusing to migrate/],
  ["corrupt-get", /Stored backup does not match/],
  ["get", /Could not read the stored backup back/],
]) {
  test(`backup failure (${failure}) stops the deployment before migrations`, async () => {
    const api = await cloudflareApi({ ownedHosts: [{ host: "academy.agroai-pilot.com", service: "agroai-academy" }] });
    const ws = await liveProduction(api);
    const deployedBefore = json(ws, "deployed-production.json").at;
    const r = await run(ws, "production", api, { ...prod, FAKE_FAIL: failure });
    api.close();
    assert.notEqual(r.code, 0);
    assert.match(r.out, message);
    assert.doesNotMatch(r.calls, /migrations apply/);
    assert.equal(json(ws, "deployed-production.json").at, deployedBefore, "Worker not redeployed");
    const db = new DatabaseSync(join(ws.state, "d1-agroai-academy.sqlite"));
    assert.equal(db.prepare("SELECT COUNT(*) AS n FROM users").get().n, 2, "learner data untouched");
    assert.equal(db.prepare("SELECT COUNT(*) AS n FROM attempts").get().n, 1);
    db.close();
  });
}

test("learners writing during the export do not fail an exact backup", async () => {
  const api = await cloudflareApi({ ownedHosts: [{ host: "academy.agroai-pilot.com", service: "agroai-academy" }] });
  const ws = await liveProduction(api);
  const r = await run(ws, "production", api, { ...prod, FAKE_FAIL: "concurrent-signup,concurrent-deletion,concurrent-grading" });
  api.close();
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /note: table users: 1 record\(s\) changed during the export/);
  assert.match(r.out, /note: table attempts: 1 record\(s\) changed during the export/);
  assert.match(r.out, /Critical records verified exactly: users=1, enrollments=1, attempts=0, certificates=1/);
});

test("pending migrations are rehearsed on the restored copy before touching live data", async () => {
  const api = await cloudflareApi({ ownedHosts: [{ host: "academy.agroai-pilot.com", service: "agroai-academy" }] });
  const ws = await liveProduction(api);
  // A migration that only fails on real data: a new unique index the existing rows violate.
  writeFileSync(join(ws.dir, "migrations", "9999_synthetic_unique_title.sql"), "CREATE UNIQUE INDEX synthetic_unique_display ON users(created_at);\n");
  const db = new DatabaseSync(join(ws.state, "d1-agroai-academy.sqlite"));
  db.exec("UPDATE users SET created_at = '2026-01-01T00:00:00.000Z'");
  db.close();
  const r = await run(ws, "production", api, prod);
  api.close();
  assert.notEqual(r.code, 0);
  assert.match(r.out, /migration 9999_synthetic_unique_title\.sql fails on the restored data/);
  assert.doesNotMatch(r.calls, /migrations apply/);
});

test("production needs an escrowed signing key and never stores an unencrypted backup: missing either, no deploy", async () => {
  const api = await cloudflareApi({ ownedHosts: [{ host: "academy.agroai-pilot.com", service: "agroai-academy" }] });
  const ws = await liveProduction(api);
  const deployedBefore = json(ws, "deployed-production.json").at;
  for (const [extra, message] of [
    [{ BACKUP_PASSPHRASE: "" }, /BACKUP_PASSPHRASE is required for production/],
    [{ BACKUP_PASSPHRASE: "too short" }, /at least 20 characters/],
    [{ CERT_SIGNING_SECRET: "" }, /CERT_SIGNING_SECRET .* is required for production/],
    [{ CERT_SIGNING_SECRET: "short" }, /CERT_SIGNING_SECRET .* is required for production/],
  ]) {
    const r = await run(ws, "production", api, { ...prod, ...extra });
    assert.equal(r.code, 1, r.out);
    assert.match(r.out, message);
    assert.equal(r.calls, "", "no Cloudflare command ran");
  }
  api.close();
  assert.equal(json(ws, "deployed-production.json").at, deployedBefore, "Worker not redeployed");
  assert.ok(!existsSync(join(ws.state, "r2", "agroai-academy-backups")), "no backup stored");
});

test("production backups are encrypted, and the stored copy is decrypted and compared before migrations", async () => {
  const api = await cloudflareApi({ ownedHosts: [{ host: "academy.agroai-pilot.com", service: "agroai-academy" }] });
  const ws = await liveProduction(api);
  const r = await run(ws, "production", api, prod);
  api.close();
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /Backup encryption: GPG AES-256 self-test passed/);
  assert.match(r.out, /Encrypted backup decrypted from the stored copy and matches the verified export/);
  const dir = join(ws.state, "r2", "agroai-academy-backups", "d1", "agroai-academy");
  const file = readdirSync(dir).find((f) => f.endsWith(".sql.gz.gpg"));
  assert.ok(file, "encrypted object stored");
  assert.ok(!readdirSync(dir).some((f) => f.endsWith(".sql.gz")), "no plain copy stored");
  assert.doesNotMatch(readFileSync(join(dir, file)).toString("latin1"), /grower@academy\.test|CREATE TABLE/, "ciphertext only");
  assert.match(gunzipSync(gpgDecrypt(ws, join(dir, file))).toString("utf8"), /grower@academy\.test/);
  assert.doesNotMatch(r.out, /synthetic test passphrase/);
});

test("a missing signing key is never regenerated while certificates exist", async () => {
  const api = await cloudflareApi({ ownedHosts: [{ host: "academy.agroai-pilot.com", service: "agroai-academy" }] });
  const ws = await liveProduction(api);
  writeFileSync(join(ws.state, "secrets-production.json"), "{}");
  const r = await run(ws, "production", api, prod);
  api.close();
  assert.equal(r.code, 1);
  assert.match(r.out, /1 certificate\(s\) exist but the Worker has no CERT_SIGNING_SECRET/);
  assert.deepEqual(json(ws, "secrets-production.json"), {});
});

test("an unreadable secret list never leads to a new signing key", async () => {
  const api = await cloudflareApi({ ownedHosts: [{ host: "academy.agroai-pilot.com", service: "agroai-academy" }] });
  const ws = await liveProduction(api);
  const before = json(ws, "secrets-production.json");
  const r = await run(ws, "production", api, { ...prod, FAKE_FAIL: "secret-list" });
  api.close();
  assert.equal(r.code, 1);
  assert.match(r.out, /Could not list Worker secrets; refusing to change them/);
  assert.deepEqual(json(ws, "secrets-production.json"), before);
});

test("an unrelated DNS record on the hostname stops the deployment", async () => {
  const api = await cloudflareApi({ foreignHost: "academy-staging.agroai-pilot.com" });
  const ws = workspace();
  const r = await run(ws, "staging", api);
  api.close();
  assert.equal(r.code, 1);
  assert.match(r.out, /already has a DNS record that is not this Worker's custom domain/);
  assert.equal(r.calls, "", "nothing created or deployed");
});

test("a token without DNS read permission falls back to public DNS", async () => {
  // No public record: the deployment proceeds and the custom domain is created.
  let api = await cloudflareApi({ dnsForbidden: true });
  let r = await run(workspace(), "staging", api);
  api.close();
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /Token cannot read DNS records; public DNS shows 0 record\(s\)/);
  // A public record that is not this Worker stops it before anything is created.
  api = await cloudflareApi({ dnsForbidden: true, publicHosts: ["academy-staging.agroai-pilot.com"] });
  const ws = workspace();
  r = await run(ws, "staging", api);
  api.close();
  assert.equal(r.code, 1);
  assert.match(r.out, /already has a DNS record that is not this Worker's custom domain/);
  assert.equal(r.calls, "", "nothing created or deployed");
});

function runRestore(ws, args, extraEnv = {}) {
  return new Promise((resolve) => {
    const child = spawn("bash", [join(root, "scripts/restore-backup.sh"), ...args], {
      cwd: ws.dir,
      env: { PATH: process.env.PATH, HOME: ws.dir, ACADEMY_WRANGLER: `node ${FAKE}`, FAKE_STATE: ws.state, BACKUP_PASSPHRASE: PASS, ...extraEnv },
    });
    let out = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (out += d));
    child.on("close", (code) => resolve({ code, out }));
  });
}

test("a stored backup restores into a new database without touching the live one", async () => {
  const api = await cloudflareApi({ ownedHosts: [{ host: "academy.agroai-pilot.com", service: "agroai-academy" }] });
  const ws = await liveProduction(api);
  const r = await run(ws, "production", api, prod);
  api.close();
  assert.equal(r.code, 0, r.out);
  const key = /Stored (agroai-academy-backups\/\S+) \(sha256 ([0-9a-f]{64})\)/.exec(r.out);
  assert.ok(key, "deploy reports the backup key and checksum");

  let rr = await runRestore(ws, [key[1], "agroai-academy"]);
  assert.equal(rr.code, 2, "refuses to restore over the live database");
  rr = await runRestore(ws, [key[1], "agroai-academy-restore-drill", "f".repeat(64)]);
  assert.equal(rr.code, 1);
  assert.match(rr.out, /Checksum mismatch/);
  rr = await runRestore(ws, [key[1], "agroai-academy-restore-drill", key[2]]);
  assert.equal(rr.code, 0, rr.out);
  const restored = new DatabaseSync(join(ws.state, "d1-agroai-academy-restore-drill.sqlite"));
  assert.equal(restored.prepare("SELECT email FROM users").get().email, "grower@academy.test");
  assert.equal(restored.prepare("SELECT credential_id FROM certificates").get().credential_id, "AGA-AAAA-BBBB-CCCC");
  assert.ok(restored.prepare("SELECT COUNT(*) AS n FROM lessons").get().n > 0);
  restored.close();
  assert.match(rr.out, /Every table's row count and every critical record match the backup/);
  rr = await runRestore(ws, [key[1], "agroai-academy-restore-drill"]);
  assert.equal(rr.code, 2, "never restores into an existing database");
  // An import that silently loses certificates is caught.
  rr = await runRestore(ws, [key[1], "agroai-academy-restore-drill-2"], { FAKE_FAIL: "lossy-import" });
  assert.equal(rr.code, 1);
  assert.match(rr.out, /Restored row counts differ from the backup/);
});
