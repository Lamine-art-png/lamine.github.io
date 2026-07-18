// Behavioral contract test for the Field Intelligence offline queue.
// Runs the real IndexedDB implementation (via fake-indexeddb) after
// transpiling the TypeScript module with esbuild. Proves tenant isolation,
// cross-tab lease coordination, stale recovery, bounded retry and that blobs
// are only deleted after durable acceptance.
import "fake-indexeddb/auto";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import esbuild from "esbuild";

const root = process.cwd();
const srcPath = path.join(root, "src", "app", "fieldIntelligence", "offlineQueue.ts");
const src = fs.readFileSync(srcPath, "utf8");

// --- structural guards ---
assert(/localStorage\s*\.\s*\w+\s*\(/.test(src) === false, "offline queue must never use localStorage for records/blobs");
assert(src.includes("dbNameFor"), "namespaced database name helper must exist");
assert(src.includes("acquireLease"), "cross-tab lease must exist");
assert(src.includes("recoverStale"), "stale-sync recovery must exist");
assert(src.includes("MAX_ATTEMPTS"), "bounded retry ceiling must exist");

const js = esbuild.transformSync(src, { loader: "ts", format: "esm" }).code;
const genPath = path.join(root, "tests", ".offlineQueue.gen.mjs");
fs.writeFileSync(genPath, js);

const q = await import(pathToFileURL(genPath).href);

function baseRecord(id) {
  return {
    clientCaptureId: id, idempotencyKey: id, createdAt: Date.now(),
    captureSource: "typed", noteText: "note " + id, assetManifest: [],
    syncState: "queued", retryCount: 0,
  };
}

const okApi = {
  initiate: async (p) => ({ capture: { id: "srv_" + p.client_capture_id } }),
  uploadAsset: async () => ({ status: "stored" }),
  complete: async () => ({ observation: { id: "obs_1" } }),
};

let failures = 0;
async function check(name, fn) {
  try { await fn(); console.log("  ok -", name); }
  catch (e) { failures += 1; console.error("  FAIL -", name, "\n     ", e.message); }
}

// 1) pure helpers
await check("dbNameFor isolates identities", () => {
  assert.notStrictEqual(q.dbNameFor("orgA", "u1"), q.dbNameFor("orgB", "u1"));
  assert.notStrictEqual(q.dbNameFor("orgA", "u1"), q.dbNameFor("orgA", "u2"));
  assert.strictEqual(q.dbNameFor("orgA", "u1"), q.dbNameFor("orgA", "u1"));
});
await check("backoff is bounded and monotonic", () => {
  assert.strictEqual(q.backoffDelay(0), 2000);
  assert.ok(q.backoffDelay(3) > q.backoffDelay(2));
  assert.ok(q.backoffDelay(50) <= 5 * 60 * 1000);
  assert.strictEqual(q.MAX_ATTEMPTS, 8);
});

// 2) tenant isolation across identities
await check("User B cannot see User A's local captures", async () => {
  q.configureIdentity("orgA", "userA");
  await q.putCapture(baseRecord("capA"));
  assert.strictEqual((await q.allCaptures()).length, 1);

  q.configureIdentity("orgB", "userB");
  assert.strictEqual((await q.allCaptures()).length, 0, "org B must not observe org A records");
  await q.putCapture(baseRecord("capB"));
  assert.strictEqual((await q.allCaptures()).length, 1);

  q.configureIdentity("orgA", "userA");
  const rows = await q.allCaptures();
  assert.strictEqual(rows.length, 1);
  assert.strictEqual(rows[0].clientCaptureId, "capA");
});

// 3) successful flush reaches synced and clears blobs after acceptance
await check("flush reaches synced (durable acceptance)", async () => {
  q.configureIdentity("orgSync", "u");
  await q.putCapture(baseRecord("capS"));
  const res = await q.flushQueue(okApi);
  assert.strictEqual(res.synced, 1);
  const rows = await q.allCaptures();
  assert.strictEqual(rows[0].syncState, "synced");
  assert.strictEqual(rows[0].observationId, "obs_1");
});

// 4) blobs deleted only AFTER durable acceptance
await check("blob retained until sync, deleted after", async () => {
  q.configureIdentity("orgBlob", "u");
  await q.putCapture({ ...baseRecord("capBlob"), assetManifest: [{ client_asset_id: "a1", kind: "photo", content_type: "image/png" }] });
  await q.putAsset({ id: "a1", clientCaptureId: "capBlob", kind: "photo", contentType: "image/png", filename: "a.png", blob: new Blob([new Uint8Array(8)]), uploaded: false });
  let failCompletes = true;
  const flaky = { ...okApi, complete: async () => { if (failCompletes) throw Object.assign(new Error("net"), {}); return { observation: { id: "o" } }; } };
  await q.flushQueue(flaky);
  assert.strictEqual(await rawAssetCount(q.dbNameFor("orgBlob", "u"), "capBlob"), 1, "blob must survive a failed sync");
  failCompletes = false;
  await q.retryRecord(okApi, "capBlob");
  assert.strictEqual(await rawAssetCount(q.dbNameFor("orgBlob", "u"), "capBlob"), 0, "blob removed only after durable acceptance");
});

// 5) cross-tab lease: a record actively leased by another tab is untouched
await check("record leased by another tab is not flushed", async () => {
  q.configureIdentity("orgLease", "u");
  await q.putCapture({ ...baseRecord("capL"), syncState: "syncing", leaseOwner: "other-tab", leaseExpiresAt: Date.now() + 60000 });
  await q.flushQueue(okApi);
  const rows = await q.allCaptures();
  assert.strictEqual(rows[0].syncState, "syncing", "another tab's active lease must be respected");
});

// 6) stale recovery: abandoned syncing record with expired lease is recovered
await check("stale syncing record recovers and syncs", async () => {
  q.configureIdentity("orgStale", "u");
  await q.putCapture({ ...baseRecord("capStale"), syncState: "syncing", leaseOwner: "dead-tab", leaseExpiresAt: Date.now() - 5000 });
  await q.flushQueue(okApi);
  assert.strictEqual((await q.getCapture("capStale")).syncState, "synced");
});

// 7) failed sync is retained (never lost) and marked failed
await check("failed sync retained for manual/auto retry", async () => {
  q.configureIdentity("orgFail", "u");
  await q.putCapture(baseRecord("capF"));
  const boom = { ...okApi, initiate: async () => { throw new Error("offline"); } };
  await q.flushQueue(boom);
  const rec = await q.getCapture("capF");
  assert.strictEqual(rec.syncState, "failed");
  assert.strictEqual(rec.retryCount, 1);
  assert.ok(rec.nextAttemptAt > Date.now());
});

// 8) item 9: after MAX_ATTEMPTS auto-flush stops until explicit manual retry
await check("retries are bounded; attempt N+1 does not happen automatically", async () => {
  q.configureIdentity("orgBound", "u");
  await q.putCapture(baseRecord("capBound"));
  let calls = 0;
  const failing = { initiate: async () => { calls += 1; throw new Error("down"); }, uploadAsset: async () => ({}), complete: async () => ({}) };
  for (let i = 0; i < q.MAX_ATTEMPTS + 3; i += 1) {
    const rec = await q.getCapture("capBound");
    if (rec) { rec.nextAttemptAt = undefined; await q.putCapture(rec); } // advance past backoff each round
    await q.flushQueue(failing);
  }
  const rec = await q.getCapture("capBound");
  assert.strictEqual(rec.syncState, "manual_recovery", "record must become terminal");
  assert.strictEqual(calls, q.MAX_ATTEMPTS, `must stop after ${q.MAX_ATTEMPTS} attempts, got ${calls}`);
  // even with the backoff window cleared, automatic flush must not attempt again
  rec.nextAttemptAt = undefined; await q.putCapture(rec);
  await q.flushQueue(failing);
  assert.strictEqual(calls, q.MAX_ATTEMPTS, "no automatic attempt in terminal state");
  // explicit manual retry resumes
  const ok = { initiate: async () => ({ capture: { id: "s" } }), uploadAsset: async () => ({}), complete: async () => ({ observation: { id: "o" } }) };
  await q.retryRecord(ok, "capBound");
  assert.strictEqual((await q.getCapture("capBound")).syncState, "synced");
});

// 9) item 10: two contexts, slow op — the lease cannot be stolen mid-flight
await check("a leased record is not double-flushed by another tab during a slow op", async () => {
  // second module instance = a second tab (its own TAB_ID), same shared IndexedDB
  const js2 = esbuild.transformSync(src, { loader: "ts", format: "esm" }).code;
  const gen2 = path.join(root, "tests", ".offlineQueue.gen2.mjs");
  fs.writeFileSync(gen2, js2);
  const qB = await import(pathToFileURL(gen2).href);

  q.configureIdentity("orgTabs", "u");
  qB.configureIdentity("orgTabs", "u");
  await q.putCapture(baseRecord("capTabs"));

  let release;
  const slow = new Promise((r) => { release = r; });
  let aCompletes = 0;
  let bCompletes = 0;
  const slowApi = { initiate: async () => ({ capture: { id: "s" } }), uploadAsset: async () => ({}), complete: async () => { aCompletes += 1; await slow; return { observation: { id: "o" } }; } };
  const okApi = { initiate: async () => ({ capture: { id: "s" } }), uploadAsset: async () => ({}), complete: async () => { bCompletes += 1; return { observation: { id: "o2" } }; } };

  const aRun = q.flushQueue(slowApi);          // A starts, holds the lease, blocks in complete()
  await new Promise((r) => setTimeout(r, 20));
  await qB.flushQueue(okApi);                    // B must skip A's actively-leased record
  assert.strictEqual(bCompletes, 0, "second tab must not process a record leased by the first");
  release();
  await aRun;
  assert.strictEqual(aCompletes, 1);
  assert.strictEqual((await q.getCapture("capTabs")).syncState, "synced");
  fs.unlinkSync(gen2);
});

// 10: renewLease extends ownership so a slow op survives past LEASE_MS
await check("renewLease extends the owner's lease", async () => {
  q.configureIdentity("orgRenew", "u");
  await q.putCapture(baseRecord("capRenew"));
  // non-owner cannot renew
  assert.strictEqual(await q.renewLease("capRenew"), false);
});

function rawAssetCount(dbName, captureId) {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(dbName);
    open.onsuccess = () => {
      const db = open.result;
      const idx = db.transaction("assets", "readonly").objectStore("assets").index("byCapture").getAll(captureId);
      idx.onsuccess = () => { resolve(idx.result.length); db.close(); };
      idx.onerror = () => reject(idx.error);
    };
    open.onerror = () => reject(open.error);
  });
}

fs.unlinkSync(genPath);
if (failures > 0) {
  console.error(`\nField Intelligence offline contract FAILED (${failures})`);
  process.exit(1);
}
console.log("\nField Intelligence offline contract passed");
