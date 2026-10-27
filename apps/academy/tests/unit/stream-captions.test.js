// Stream's player must only ever carry production's reviewed captions, and
// staging must never change the tracks of the shared uploads
// (scripts/stream.mjs). The Stream API is stubbed; nothing leaves the process.
import { test } from "node:test";
import assert from "node:assert/strict";

process.env.STREAM_API_TOKEN = "test-token-not-real";
process.env.CLOUDFLARE_ACCOUNT_ID = "acct";
process.env.STREAM_GENERATE_CAPTIONS = "1";
const { syncCaptions } = await import("../../scripts/stream.mjs");

const UID = "0123456789abcdef0123456789abcdef";
const VIDEO = { id: "vid_a1_data", n: 4 };

/** In-memory Stream captions for one video, behind a fetch stub. */
function fakeStream(initial) {
  const caps = new Map(initial.map((c) => [c.language, { ...c }]));
  const calls = [];
  globalThis.fetch = async (url, { method = "GET", body } = {}) => {
    const path = new URL(url).pathname.replace(/^.*\/stream\/[0-9a-f]{32}/, "");
    calls.push(`${method} ${path}`);
    const ok = (result) => new Response(JSON.stringify({ success: true, result }), { status: 200 });
    let m;
    if (path === "/captions" && method === "GET") return ok([...caps.values()].map(({ vtt, ...c }) => c));
    if ((m = /^\/captions\/(\w+)\/generate$/.exec(path))) {
      caps.set(m[1], { language: m[1], generated: true, status: "ready", vtt: "WEBVTT\n\n00:00.000 --> 00:01.000\nmachine text" });
      return ok({});
    }
    if ((m = /^\/captions\/(\w+)\/vtt$/.exec(path))) return new Response(caps.get(m[1])?.vtt || "", { status: 200 });
    if ((m = /^\/captions\/(\w+)$/.exec(path)) && method === "DELETE") {
      caps.delete(m[1]);
      return ok({});
    }
    if ((m = /^\/captions\/(\w+)$/.exec(path)) && method === "PUT") {
      caps.set(m[1], { language: m[1], generated: false, status: "ready", vtt: await body.get("file").text() });
      return ok({});
    }
    throw new Error(`unexpected ${method} ${path}`);
  };
  return { caps, calls };
}

const WRITER = { writer: true };
const REVIEWED_EN = "WEBVTT\n\n00:00.000 --> 00:01.000\nReviewed English.";
const writes = (calls) => calls.filter((c) => !c.startsWith("GET "));

test("a generated English caption is imported as a draft and removed from Stream's player", async () => {
  const { caps } = fakeStream([{ language: "en", generated: true, status: "ready", vtt: "WEBVTT\n\n00:00.000 --> 00:01.000\nmachine text" }]);
  const drafts = [];
  const res = await syncCaptions(UID, VIDEO, { readyToStream: true }, [], drafts, [], WRITER);
  assert.equal(drafts.length, 1);
  assert.match(drafts[0], /'machine'/);
  assert.match(drafts[0], /machine text/);
  assert.doesNotMatch(drafts[0], /'reviewed'/, "never marked reviewed");
  assert.match(drafts[0], /WHERE NOT EXISTS \(SELECT 1 FROM lessons l JOIN courses c/, "released media is never changed");
  assert.match(drafts[0], /DO UPDATE SET vtt = excluded.vtt WHERE video_captions.status = 'machine'/, "an import never overwrites a reviewed caption");
  assert.equal(caps.size, 0, "no unreviewed caption stays in the player");
  assert.deepEqual(res.problems, []);
});

test("production asks Stream for an English draft once, and only when no English caption exists", async () => {
  const { calls } = fakeStream([]);
  const pending = [];
  await syncCaptions(UID, VIDEO, { readyToStream: true }, [], [], pending, WRITER);
  assert.ok(calls.includes("POST /captions/en/generate"));
  assert.equal(pending.length, 1, "the draft is collected (or removed) at the end of the run");
  const again = fakeStream([]);
  await syncCaptions(UID, VIDEO, { readyToStream: true }, [{ video_id: VIDEO.id, locale: "en", status: "machine", vtt: null }], [], [], WRITER);
  assert.ok(!again.calls.some((c) => c.includes("/generate")), "an existing draft is not generated again");
});

test("reviewed captions in any language replace machine ones in the player", async () => {
  const { caps } = fakeStream([{ language: "en", generated: true, status: "ready", vtt: "WEBVTT\n\nmachine" }]);
  const rows = [
    { video_id: VIDEO.id, locale: "en", status: "reviewed", vtt: REVIEWED_EN },
    { video_id: VIDEO.id, locale: "fr-FR", status: "reviewed", vtt: "WEBVTT\n\n00:00.000 --> 00:01.000\nFrançais relu." },
  ];
  const drafts = [];
  const res = await syncCaptions(UID, VIDEO, { readyToStream: true }, rows, drafts, [], WRITER);
  assert.equal(caps.get("en").generated, false);
  assert.match(caps.get("en").vtt, /Reviewed English/);
  assert.match(caps.get("fr").vtt, /Français relu/);
  assert.equal(drafts.length, 0, "a reviewed caption is never overwritten by a draft");
  assert.deepEqual(res.problems, []);
});

test("P2: every track of any language that is not a reviewed caption is removed from the player", async () => {
  const { caps } = fakeStream([
    { language: "es", generated: true, status: "ready", vtt: "WEBVTT\n\nmáquina" },
    { language: "fr", generated: false, status: "ready", vtt: "WEBVTT\n\nmanual upload, never reviewed" },
    { language: "en", generated: false, status: "ready", vtt: "WEBVTT\n\nedited directly in Cloudflare" },
    { language: "pt", generated: false, status: "ready", vtt: "WEBVTT\n\nmanual" },
  ]);
  const rows = [
    { video_id: VIDEO.id, locale: "en", status: "reviewed", vtt: REVIEWED_EN },
    { video_id: VIDEO.id, locale: "pt-BR", status: "machine", vtt: null },
    { video_id: VIDEO.id, locale: "fr", status: "draft", vtt: null },
  ];
  const res = await syncCaptions(UID, VIDEO, { readyToStream: true }, rows, [], [], WRITER);
  assert.deepEqual([...caps.keys()], ["en"], "only the reviewed caption is playable");
  assert.equal(caps.get("en").vtt.trim(), REVIEWED_EN, "a track edited outside the Academy is replaced by the reviewed text");
  assert.deepEqual(res.problems, []);
});

test("P2: with no reviewed caption, a manually uploaded track is removed", async () => {
  const { caps } = fakeStream([{ language: "de", generated: false, status: "ready", vtt: "WEBVTT\n\nmanual" }]);
  await syncCaptions(UID, VIDEO, { readyToStream: true }, [{ video_id: VIDEO.id, locale: "en", status: "machine", vtt: null }], [], [], WRITER);
  assert.equal(caps.size, 0);
});

test("reviewed captions already in the player are preserved untouched on every redeploy", async () => {
  const { calls, caps } = fakeStream([{ language: "en", generated: false, status: "ready", vtt: REVIEWED_EN + "\n" }]);
  const res = await syncCaptions(UID, VIDEO, { readyToStream: true }, [{ video_id: VIDEO.id, locale: "en", status: "reviewed", vtt: REVIEWED_EN }], [], [], WRITER);
  assert.deepEqual(writes(calls), [], "no delete, upload or generation");
  assert.equal(caps.get("en").vtt.trim(), REVIEWED_EN);
  assert.deepEqual(res.problems, []);
});

test("two reviewed locales sharing one Stream language are not published, and the run reports it", async () => {
  const { caps } = fakeStream([]);
  const rows = [
    { video_id: VIDEO.id, locale: "en", status: "reviewed", vtt: REVIEWED_EN },
    { video_id: VIDEO.id, locale: "pt-BR", status: "reviewed", vtt: "WEBVTT\n\nBR" },
    { video_id: VIDEO.id, locale: "pt-PT", status: "reviewed", vtt: "WEBVTT\n\nPT" },
  ];
  const res = await syncCaptions(UID, VIDEO, { readyToStream: true }, rows, [], [], WRITER);
  assert.deepEqual([...caps.keys()], ["en"]);
  assert.match(res.problems.join(), /several reviewed captions for "pt"/);
});

test("P1: staging (read-only) never uploads, deletes or generates a track, even with its own reviewed captions", async () => {
  const production = [
    { language: "en", generated: false, status: "ready", vtt: REVIEWED_EN },
    { language: "fr", generated: false, status: "ready", vtt: "WEBVTT\n\nFrançais relu (production)." },
  ];
  const { calls, caps } = fakeStream(production);
  const stagingRows = [
    { video_id: VIDEO.id, locale: "en", status: "reviewed", vtt: "WEBVTT\n\n00:00.000 --> 00:01.000\nStaging rehearsal edit." },
    { video_id: VIDEO.id, locale: "es", status: "reviewed", vtt: "WEBVTT\n\nEnsayo." },
  ];
  const drafts = [];
  const pending = [];
  const res = await syncCaptions(UID, VIDEO, { readyToStream: true }, stagingRows, drafts, pending, { writer: false });
  assert.deepEqual(writes(calls), [], "only reads");
  assert.equal(caps.get("en").vtt, REVIEWED_EN, "production's reviewed English is unchanged");
  assert.ok(caps.get("fr") && !caps.has("es"), "nothing added or removed");
  assert.equal(drafts.length + pending.length, 0, "staging imports and requests nothing from the shared upload");
  assert.match(res.desc, /read-only/);
  assert.deepEqual(res.problems, []);
});

test("P1: staging with no captions at all does not ask Stream to generate one", async () => {
  process.env.STREAM_GENERATE_CAPTIONS = "1";
  const { calls } = fakeStream([]);
  await syncCaptions(UID, VIDEO, { readyToStream: true }, [], [], [], { writer: false });
  assert.deepEqual(writes(calls), []);
});

test("the read-only mode is the default", async () => {
  const { calls } = fakeStream([{ language: "fr", generated: false, status: "ready", vtt: "WEBVTT\n\nmanual" }]);
  await syncCaptions(UID, VIDEO, { readyToStream: true }, [], [], []);
  assert.deepEqual(writes(calls), []);
});
