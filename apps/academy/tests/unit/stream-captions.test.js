// Stream's player must only ever carry reviewed captions (scripts/stream.mjs).
// The Stream API is stubbed; nothing leaves the process.
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

test("a generated English caption is imported as a draft and removed from Stream's player", async () => {
  const { caps } = fakeStream([]);
  const drafts = [];
  const pending = [];
  await syncCaptions(UID, VIDEO, { readyToStream: true }, [], drafts, pending);
  assert.equal(drafts.length, 1);
  assert.match(drafts[0], /'machine'/);
  assert.match(drafts[0], /machine text/);
  assert.doesNotMatch(drafts[0], /'reviewed'/, "never marked reviewed");
  assert.match(drafts[0], /WHERE NOT EXISTS \(SELECT 1 FROM lessons l JOIN courses c/, "released media is never changed");
  assert.equal(caps.size, 0, "no unreviewed caption stays in the player");
});

test("once a draft exists in the Academy, nothing is generated again", async () => {
  const { calls } = fakeStream([]);
  await syncCaptions(UID, VIDEO, { readyToStream: true }, [{ video_id: VIDEO.id, locale: "en", status: "machine", vtt: null }], [], []);
  assert.ok(!calls.some((c) => c.includes("/generate")));
});

test("reviewed captions in any language replace machine ones in the player", async () => {
  const { caps } = fakeStream([{ language: "en", generated: true, status: "ready", vtt: "WEBVTT\n\nmachine" }]);
  const rows = [
    { video_id: VIDEO.id, locale: "en", status: "reviewed", vtt: "WEBVTT\n\n00:00.000 --> 00:01.000\nReviewed English." },
    { video_id: VIDEO.id, locale: "fr-FR", status: "reviewed", vtt: "WEBVTT\n\n00:00.000 --> 00:01.000\nFrançais relu." },
  ];
  const drafts = [];
  await syncCaptions(UID, VIDEO, { readyToStream: true }, rows, drafts, []);
  assert.equal(caps.get("en").generated, false);
  assert.match(caps.get("en").vtt, /Reviewed English/);
  assert.match(caps.get("fr").vtt, /Français relu/);
  assert.equal(drafts.length, 0, "a reviewed caption is never overwritten by a draft");
});
