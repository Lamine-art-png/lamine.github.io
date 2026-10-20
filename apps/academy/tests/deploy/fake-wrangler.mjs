#!/usr/bin/env node
// A local stand-in for the wrangler commands scripts/deploy.sh uses, backed by
// SQLite files and a directory acting as R2. Lets the deploy script's safety
// logic (backup, verification, secret guards) be tested without Cloudflare.
// State lives in $FAKE_STATE. $FAKE_FAIL selects an injected failure.
import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync, copyFileSync, appendFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { createHash, randomUUID } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { dumpDatabase } from "./sqlite-dump.mjs";

const STATE = process.env.FAKE_STATE;
const FAIL = new Set(String(process.env.FAKE_FAIL || "").split(",").filter(Boolean));
const argv = process.argv.slice(2);
const flag = (name) => {
  const i = argv.indexOf(name);
  return i >= 0 ? argv[i + 1] : undefined;
};
const has = (name) => argv.includes(name);
const env = flag("--env") || "production";
const log = (line) => appendFileSync(join(STATE, "calls.log"), `${line}\n`);
const readJson = (f, d) => (existsSync(join(STATE, f)) ? JSON.parse(readFileSync(join(STATE, f), "utf8")) : d);
const writeJson = (f, v) => writeFileSync(join(STATE, f), JSON.stringify(v, null, 2));
const dbFile = (name) => join(STATE, `d1-${name}.sqlite`);
const fail = (msg) => {
  process.stderr.write(`✘ [ERROR] ${msg}\n`);
  process.exit(1);
};

log(argv.join(" "));
const [group, sub, third] = argv;

if (group === "d1" && sub === "list") {
  process.stdout.write(JSON.stringify(readJson("d1.json", [])));
} else if (group === "d1" && sub === "create") {
  const list = readJson("d1.json", []);
  list.push({ uuid: randomUUID(), name: third });
  writeJson("d1.json", list);
  new DatabaseSync(dbFile(third)).close();
} else if (group === "d1" && sub === "execute") {
  if (FAIL.has("execute")) fail("execute failed");
  const db = new DatabaseSync(dbFile(third), { enableForeignKeyConstraints: false });
  if (flag("--file")) {
    let sql = readFileSync(flag("--file"), "utf8");
    if (FAIL.has("lossy-import")) sql = sql.split("\n").filter((l) => !/^INSERT INTO "certificates"/.test(l)).join("\n");
    db.exec(sql);
    db.close();
    process.stdout.write(JSON.stringify([{ results: [], success: true, meta: {} }]));
  } else {
    // Cloudflare D1 rejects compound SELECTs beyond a few terms (seen live: 11 terms failed).
    if ((flag("--command").match(/\bUNION\b/gi) || []).length >= 4) {
      db.close();
      process.stdout.write(JSON.stringify({ error: { text: "A request to the Cloudflare API failed.", notes: [{ text: "too many terms in compound SELECT: SQLITE_ERROR [code: 7500]" }] } }));
      process.exit(1);
    }
    const results = db.prepare(flag("--command")).all();
    db.close();
    process.stdout.write(JSON.stringify([{ results, success: true, meta: {} }]));
  }
} else if (group === "d1" && sub === "time-travel") {
  if (FAIL.has("timetravel")) fail("time travel unavailable");
  process.stdout.write(JSON.stringify({ bookmark: "00000085-0000024c-00004c6d-fake", timestamp: new Date().toISOString() }));
} else if (group === "d1" && sub === "export") {
  if (FAIL.has("export")) fail("export failed");
  // Learners keep using the Academy while the export runs.
  const live = new DatabaseSync(dbFile(argv[2]), { enableForeignKeyConstraints: false });
  const now = new Date().toISOString();
  if (FAIL.has("concurrent-signup")) live.prepare("INSERT INTO users (id, email, display_name, created_at, updated_at) VALUES ('usr_new', 'new@academy.test', 'Synthetic New', ?, ?)").run(now, now);
  if (FAIL.has("concurrent-deletion")) live.exec("DELETE FROM users WHERE id = 'usr_2'");
  if (FAIL.has("concurrent-grading")) live.exec("UPDATE attempts SET status = 'graded', score_pct = 90, passed = 1 WHERE id = 'att_1'");
  if (FAIL.has("certificate-vanishes")) live.exec("DELETE FROM certificates WHERE id = 'crt_1'");
  live.close();
  let sql = dumpDatabase(argv[2] && dbFile(argv[2]));
  const drop = (re) => (sql = sql.split("\n").filter((l) => !re.test(l)).join("\n"));
  if (FAIL.has("truncated-export")) sql = sql.slice(0, Math.floor(sql.length / 2));
  if (FAIL.has("lossy-export")) drop(/^INSERT INTO "users"/);
  // Single-record losses that a count tolerance would have accepted.
  if (FAIL.has("drop-one-certificate")) drop(/^INSERT INTO "certificates".*'crt_1'/);
  if (FAIL.has("drop-one-attempt")) drop(/^INSERT INTO "attempts".*'att_1'/);
  if (FAIL.has("drop-one-enrollment")) drop(/^INSERT INTO "enrollments".*'enr_1'/);
  // Row kept, frozen attempt policy lost: scoring would fall back to live settings after a restore.
  if (FAIL.has("strip-attempt-snapshot")) sql = sql.replace(`'{"passing_score":80}'`, "NULL");
  if (FAIL.has("alter-certificate")) sql = sql.replace(/'0{64}'/, `'${"1".repeat(64)}'`);
  writeFileSync(flag("--output"), sql);
} else if (group === "d1" && sub === "migrations" && third === "apply") {
  if (FAIL.has("migrate")) fail("migration failed");
  const db = new DatabaseSync(dbFile(argv[3]));
  db.exec("CREATE TABLE IF NOT EXISTS d1_migrations (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)");
  const dir = join(dirname(flag("--config")), "migrations");
  const done = new Set(db.prepare("SELECT name FROM d1_migrations").all().map((r) => r.name));
  for (const f of readdirSync(dir).filter((x) => x.endsWith(".sql")).sort()) {
    if (done.has(f)) continue;
    db.exec(readFileSync(join(dir, f), "utf8"));
    db.prepare("INSERT INTO d1_migrations (name) VALUES (?)").run(f);
  }
  db.close();
} else if (group === "deploy") {
  const toml = readFileSync(flag("--config"), "utf8");
  writeJson(`deployed-${env}.json`, { env, config: toml, at: new Date().toISOString() });
} else if (group === "secret" && sub === "list") {
  if (FAIL.has("secret-list")) fail("could not list secrets");
  process.stdout.write(JSON.stringify(Object.keys(readJson(`secrets-${env}.json`, {})).map((name) => ({ name, type: "secret_text" }))));
} else if (group === "secret" && sub === "put") {
  const value = readFileSync(0, "utf8");
  const secrets = readJson(`secrets-${env}.json`, {});
  // Only a fingerprint is kept, never the value.
  secrets[third] = { length: value.length, sha256: createHash("sha256").update(value).digest("hex") };
  writeJson(`secrets-${env}.json`, secrets);
} else if (group === "r2" && sub === "bucket" && third === "list") {
  if (FAIL.has("r2")) fail("r2 unavailable");
  process.stdout.write(readJson("buckets.json", []).map((b) => `name:           ${b}\ncreation_date:  2026-10-01T00:00:00.000Z\n`).join("\n"));
} else if (group === "r2" && sub === "bucket" && third === "create") {
  writeJson("buckets.json", [...readJson("buckets.json", []), argv[3]]);
} else if (group === "r2" && sub === "object") {
  const [bucket, ...rest] = argv[3].split("/");
  const path = join(STATE, "r2", bucket, ...rest);
  if (!has("--remote")) fail("object commands must target --remote storage in these tests");
  if (!readJson("buckets.json", []).includes(bucket)) fail(`bucket ${bucket} does not exist`);
  if (third === "put") {
    if (FAIL.has("put")) fail("upload failed");
    mkdirSync(dirname(path), { recursive: true });
    copyFileSync(flag("--file"), path);
  } else if (third === "get") {
    if (FAIL.has("get")) fail("download failed");
    copyFileSync(path, flag("--file"));
    if (FAIL.has("corrupt-get")) appendFileSync(flag("--file"), "x");
  }
} else {
  fail(`fake wrangler does not implement: ${argv.join(" ")}`);
}
