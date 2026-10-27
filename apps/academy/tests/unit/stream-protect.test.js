// The whole Stream protection run (scripts/stream.mjs protect) against an
// in-memory Stream account: a slow API, an unexpected upload, and the caption
// writer split between production and staging. The clock is simulated, so
// "slow" costs no real time. Nothing leaves the process.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

process.env.STREAM_API_TOKEN = "test-token-not-real";
process.env.CLOUDFLARE_ACCOUNT_ID = "acct";
const { protect, clock, a1Videos } = await import("../../scripts/stream.mjs");

const CUSTOMER = "https://customer-abc12345.cloudflarestream.com";
const uidFor = (n) => n.toString(16).padStart(32, "0");
const REVIEWED_EN = "WEBVTT\n\n00:00.000 --> 00:01.000\nReviewed English.";

/**
 * In-memory Stream account behind a fetch stub. `apiDelayMs` is how long each
 * API call takes on the simulated clock; a token whose expiry has passed when
 * the request arrives is rejected as Stream does (HTTP 400, code 10005).
 */
function fakeAccount({ uploads, apiDelayMs = 0 }) {
  let now = Date.UTC(2026, 9, 27, 6, 0, 0);
  clock.now = () => now;
  clock.sleep = async (ms) => {
    now += ms;
  };
  const videos = new Map(uploads.map((u) => [u.uid, { uid: u.uid, meta: { name: u.name }, requireSignedURLs: false, allowedOrigins: [], duration: 90, readyToStream: true, status: { state: "ready" }, captions: new Map((u.captions || []).map((c) => [c.language, { ...c }])), downloads: { default: { status: "ready" } } }]));
  const writes = [];
  const tokens = new Map();
  globalThis.fetch = async (url, { method = "GET", body } = {}) => {
    const u = new URL(url);
    if (u.origin === CUSTOMER) {
      // Anonymous playback: /<uid>/... is a bare id, /<token>/manifest a signed URL.
      const [, first] = u.pathname.split("/");
      const v = videos.get(first);
      if (v) return new Response("", { status: v.requireSignedURLs ? 401 : 200 });
      const exp = tokens.get(first);
      return new Response("", { status: exp && exp > now / 1000 ? 200 : 401 });
    }
    now += apiDelayMs;
    const ok = (result) => new Response(JSON.stringify({ success: true, result }), { status: 200 });
    const path = u.pathname.replace(/^.*\/accounts\/acct/, "");
    if (path === "/stream" && method === "GET") return ok([...videos.values()].map(({ captions, downloads, ...v }) => v));
    const m = /^\/stream\/([0-9a-f]{32})(\/.*)?$/.exec(path);
    if (!m) throw new Error(`unexpected ${method} ${path}`);
    const v = videos.get(m[1]);
    const rest = m[2] || "";
    if (method !== "GET") writes.push(`${method} ${m[1].slice(-2)}${rest}`);
    if (!rest && method === "GET") return ok({ ...v, captions: undefined, downloads: undefined, playback: { hls: `${CUSTOMER}/${v.uid}/manifest/video.m3u8` } });
    if (!rest && method === "POST") {
      const b = JSON.parse(body);
      Object.assign(v, { requireSignedURLs: b.requireSignedURLs, allowedOrigins: b.allowedOrigins, meta: b.meta });
      return ok({});
    }
    if (rest === "/downloads") {
      if (method === "DELETE") v.downloads = {};
      return ok(v.downloads);
    }
    if (rest === "/token") {
      const { exp } = JSON.parse(body);
      if (exp <= now / 1000) return new Response(JSON.stringify({ success: false, errors: [{ code: 10005 }] }), { status: 400 });
      const token = `tok${tokens.size}`;
      tokens.set(token, exp);
      return ok({ token });
    }
    let c;
    if (rest === "/captions") return ok([...v.captions.values()].map(({ vtt, ...x }) => x));
    if ((c = /^\/captions\/(\w+)\/vtt$/.exec(rest))) return new Response(v.captions.get(c[1])?.vtt || "", { status: 200 });
    if ((c = /^\/captions\/(\w+)\/generate$/.exec(rest))) {
      v.captions.set(c[1], { language: c[1], generated: true, status: "ready", vtt: "WEBVTT\n\nmachine" });
      return ok({});
    }
    if ((c = /^\/captions\/(\w+)$/.exec(rest)) && method === "DELETE") {
      v.captions.delete(c[1]);
      return ok({});
    }
    if ((c = /^\/captions\/(\w+)$/.exec(rest)) && method === "PUT") {
      v.captions.set(c[1], { language: c[1], generated: false, status: "ready", vtt: await body.get("file").text() });
      return ok({});
    }
    throw new Error(`unexpected ${method} ${path}`);
  };
  return { videos, writes };
}

const a1Uploads = (extra = {}) => a1Videos().map((v) => ({ uid: uidFor(v.n), name: `Video${v.n}- ${v.title}.mp4`, ...(extra[v.n] || {}) }));
const outDir = () => mkdtempSync(join(tmpdir(), "stream-protect-"));
function captionsFile(rows) {
  const f = join(outDir(), "captions.json");
  writeFileSync(f, JSON.stringify(rows));
  return f;
}
const quiet = async (fn) => {
  const log = console.log;
  const lines = [];
  console.log = (s = "") => lines.push(String(s));
  try {
    return { code: await fn(), out: lines.join("\n") };
  } finally {
    console.log = log;
  }
};

test("a slow Stream API (10 s per call) still verifies all 14 videos: the expired-token probe has headroom", async () => {
  const { videos } = fakeAccount({ uploads: a1Uploads(), apiDelayMs: 10_000 });
  const { code, out } = await quiet(() => protect({ out: outDir(), captionsFile: captionsFile([]), captionMode: "readonly" }));
  assert.equal(code, 0, out);
  assert.match(out, /All 14 uploads verified private \(14 linked to lesson videos\); no unexpected uploads/);
  assert.doesNotMatch(out, /10005|error:/);
  for (const v of videos.values()) assert.equal(v.requireSignedURLs, true);
});

test("an expired token is still verified as refused: a token that plays after expiry fails the run", async () => {
  fakeAccount({ uploads: a1Uploads(), apiDelayMs: 10_000 });
  const real = globalThis.fetch;
  globalThis.fetch = async (url, init) => (/\/tok\d+\/manifest/.test(String(url)) ? new Response("", { status: 200 }) : real(url, init));
  const { code, out } = await quiet(() => protect({ out: outDir(), captionsFile: captionsFile([]), captionMode: "readonly" }));
  assert.equal(code, 1);
  assert.match(out, /NOT PROTECTED/);
});

test("an unexpected non-Academy upload is reported, left untouched, and fails the run", async () => {
  const uploads = [...a1Uploads(), { uid: "f".repeat(32), name: "Company webinar recording.mp4" }];
  const { videos, writes } = fakeAccount({ uploads });
  const dir = outDir();
  const { code, out } = await quiet(() => protect({ out: dir, captionsFile: captionsFile([]), captionMode: "readonly" }));
  assert.equal(code, 1, "fail closed");
  assert.match(out, /Unexpected upload "Company webinar recording.mp4" \(`ffffff…`/);
  assert.ok(!writes.some((w) => w.includes("ff/") || w.startsWith("POST ff") || w.includes(" ff")), `no write to the unexpected upload: ${writes.filter((w) => / ff/.test(w))}`);
  const odd = videos.get("f".repeat(32));
  assert.equal(odd.requireSignedURLs, false, "its settings are unchanged");
  assert.deepEqual(Object.keys(odd.downloads), ["default"], "its downloads are not deleted");
  assert.doesNotMatch(readFileSync(join(dir, "evidence.sql"), "utf8"), /ffffffff/, "no evidence or mapping is recorded for it");
  for (const n of [1, 7, 14]) assert.equal(videos.get(uidFor(n)).requireSignedURLs, true, "the A1 videos are still protected");
});

test("P1 end to end: a staging run changes no caption track on the shared uploads", async () => {
  const production = [{ language: "en", generated: false, status: "ready", vtt: REVIEWED_EN }];
  const { videos, writes } = fakeAccount({ uploads: a1Uploads({ 4: { captions: production } }) });
  process.env.STREAM_GENERATE_CAPTIONS = "1";
  const stagingRows = [{ video_id: a1Videos()[3].id, locale: "en", status: "reviewed", vtt: "WEBVTT\n\n00:00.000 --> 00:01.000\nStaging edit." }];
  const { code, out } = await quiet(() => protect({ out: outDir(), captionsFile: captionsFile(stagingRows), captionMode: "readonly" }));
  delete process.env.STREAM_GENERATE_CAPTIONS;
  assert.equal(code, 0, out);
  assert.deepEqual(writes.filter((w) => w.includes("/captions")), [], "no caption upload, deletion or generation");
  assert.equal(videos.get(uidFor(4)).captions.get("en").vtt, REVIEWED_EN, "production's reviewed caption is unchanged");
  assert.match(out, /Caption mode: read-only \(staging\)/);
});

test("P2 end to end: production leaves only reviewed captions playable", async () => {
  const stray = { 2: { captions: [{ language: "es", generated: true, status: "ready", vtt: "WEBVTT\n\nx" }] }, 9: { captions: [{ language: "fr", generated: false, status: "ready", vtt: "WEBVTT\n\nmanual" }] } };
  const { videos } = fakeAccount({ uploads: a1Uploads(stray) });
  const rows = [{ video_id: a1Videos()[8].id, locale: "en", status: "reviewed", vtt: REVIEWED_EN }];
  const { code, out } = await quiet(() => protect({ out: outDir(), captionsFile: captionsFile(rows), captionMode: "writer" }));
  assert.equal(code, 0, out);
  assert.equal(videos.get(uidFor(2)).captions.size, 0, "a stray generated Spanish track is removed");
  assert.deepEqual([...videos.get(uidFor(9)).captions.keys()], ["en"], "a manual French track is removed; the reviewed English is published");
  assert.match(out, /Caption mode: writer \(production\)/);
});

test("P2: a track production cannot remove fails the run (fail closed)", async () => {
  fakeAccount({ uploads: a1Uploads({ 5: { captions: [{ language: "de", generated: false, status: "ready", vtt: "WEBVTT\n\nmanual" }] } }) });
  const real = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) =>
    init.method === "DELETE" && /\/captions\/de$/.test(String(url)) ? new Response(JSON.stringify({ success: false, errors: [{ code: 10000 }] }), { status: 403 }) : real(url, init);
  const { code, out } = await quiet(() => protect({ out: outDir(), captionsFile: captionsFile([]), captionMode: "writer" }));
  assert.equal(code, 1);
  assert.match(out, /caption sync error/);
});

test("production refuses to write captions without the reviewed caption set", async () => {
  fakeAccount({ uploads: a1Uploads() });
  await assert.rejects(() => protect({ out: outDir(), captionMode: "writer" }), /needs --captions/);
});
