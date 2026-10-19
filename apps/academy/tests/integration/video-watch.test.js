// Watch-to-complete is measured by the server from timed heartbeats, not by a
// client-reported position plus wall-clock time. These tests replay the
// spoofing techniques a learner could use and the legitimate viewing patterns
// that must still work. Server time is simulated by moving the stored time of
// the previous heartbeat into the past.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv, registeredLearner, publishCourse } from "../helpers.js";
import { creditFor, mergeSegments, MAX_RATE } from "../../src/services/progress.js";

const LESSON = "les_a1_data";
const LENGTH = 200;

async function setup() {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  await env.DB.prepare("UPDATE video_assets SET status='approved', duration_seconds=?, mp4_url='https://media.example/a1.mp4' WHERE id='vid_a1_data'").bind(LENGTH).run();
  await env.DB.prepare("UPDATE lessons SET type='video' WHERE id=?").bind(LESSON).run();
  const u = await registeredLearner(env);
  await u.post("/courses/introduction-to-ai-in-agriculture/enroll", {});
  const beat = async (position, { playing = true, after = 0, extra = {} } = {}) => {
    if (after) {
      const w = await env.DB.prepare("SELECT last_beat_at FROM video_watch WHERE lesson_id = ?").bind(LESSON).first();
      if (w) await env.DB.prepare("UPDATE video_watch SET last_beat_at = ? WHERE lesson_id = ?").bind(new Date(Date.parse(w.last_beat_at) - after * 1000).toISOString(), LESSON).run();
    }
    const r = await u.postJson("/api/progress", { lessonId: LESSON, position, duration: LENGTH, playing, ...extra });
    assert.equal(r.status, 200);
  };
  const state = async () => ({
    progress: (await env.DB.prepare("SELECT status FROM lesson_progress WHERE lesson_id = ?").bind(LESSON).first())?.status,
    watch: await env.DB.prepare("SELECT * FROM video_watch WHERE lesson_id = ?").bind(LESSON).first(),
  });
  return { env, u, beat, state };
}

test("credit rule: forward playback up to 2× between timed beats only", () => {
  const prev = { playing: 1, last_position: 100, last_beat_at: "2026-10-18T10:00:00.000Z" };
  const at = (s) => new Date(Date.parse(prev.last_beat_at) + s * 1000).toISOString();
  assert.deepEqual(creditFor(prev, { position: 110, at: at(5), playing: true }), [100, 110], "2× over 5 s");
  assert.deepEqual(creditFor(prev, { position: 112, at: at(5), playing: true }), [100, 112], "2× with network latency (10% + 1 s margin)");
  assert.equal(creditFor(prev, { position: 112.1, at: at(5), playing: true }), null, "faster than the margin allows");
  // Regression (CI): 5 s of honest 2× playback whose heartbeats reach the server 4.6 s apart.
  assert.deepEqual(creditFor(prev, { position: 110, at: at(4.6), playing: true }), [100, 110], "latency between heartbeats");
  assert.equal(creditFor(prev, { position: 90, at: at(5), playing: true }), null, "backwards");
  assert.equal(creditFor(prev, { position: 105, at: at(1), playing: true }), null, "beats closer than 2 s while playing");
  assert.deepEqual(creditFor(prev, { position: 102, at: at(1), playing: false }), [100, 102], "a closing beat gets exactly 2× without jitter");
  assert.equal(creditFor(prev, { position: 102.1, at: at(1), playing: false }), null);
  assert.equal(creditFor(prev, { position: 300, at: at(600), playing: true }), null, "gaps over 120 s are not credited, however plausible");
  assert.equal(creditFor({ ...prev, playing: 0 }, { position: 110, at: at(5), playing: true }), null, "paused before");
  assert.equal(creditFor(null, { position: 10, at: at(5), playing: true }), null, "first beat");
  assert.deepEqual(mergeSegments([[0, 10], [5, 20], [30, 40], [40, 50]]), { segments: [[0, 20], [30, 50]], total: 40 });
  assert.equal(MAX_RATE, 2);
});

test("spoof: a single report at 95% or an explicit completion never completes", async () => {
  const { u, beat, state } = await setup();
  await beat(0);
  await beat(190, { after: 150, extra: { complete: true } });
  const r = await u.post("/learn/introduction-to-ai-in-agriculture/data-the-raw-material/complete", {});
  assert.match(r.location, /\?watch=1$/);
  const s = await state();
  assert.equal(s.progress, "started");
  assert.equal(s.watch.watched_seconds, 0, "a 190 s jump in 150 s is not credited");
  assert.ok(s.watch.rejected >= 1, "the jump is recorded as rejected");
});

test("spoof: start playback, wait, then report the end (wall-clock alone)", async () => {
  // The previous rule accepted 90% position once 45% of the length had passed since the first play.
  const { beat, state } = await setup();
  await beat(0);
  await beat(185, { after: 3600 });
  assert.equal((await state()).progress, "started");
  assert.equal((await state()).watch.watched_seconds, 0);
});

test("spoof: client-reported duration and position cannot shorten the target", async () => {
  const { beat, state } = await setup();
  await beat(0, { extra: { duration: 10 } });
  await beat(10, { after: 5, extra: { duration: 10 } });
  const s = await state();
  assert.equal(s.progress, "started");
  assert.equal(s.watch.watched_seconds, 10, "10 s of a 200 s video");
});

test("spoof: playback faster than 2×, beat floods and queued replays earn nothing extra", async () => {
  const { u, beat, state } = await setup();
  await beat(0);
  for (let p = 15; p <= 195; p += 15) await beat(p, { after: 5 }); // 3× speed
  assert.equal((await state()).watch.watched_seconds, 0);
  // Flood: many beats with no server time between them.
  await beat(0, { playing: false });
  await beat(0);
  for (let p = 1; p <= 40; p++) await beat(p);
  assert.equal((await state()).watch.watched_seconds, 0, "beats under 2 s apart are ignored");
  // An offline queue replayed at once: no server time elapsed, nothing credited.
  const reports = Array.from({ length: 40 }, (_, i) => ({ lessonId: LESSON, position: 40 + i * 4, playing: true, clientAt: new Date(Date.now() - (40 - i) * 2000).toISOString() }));
  await u.postJson("/api/progress", { reports });
  assert.equal((await state()).watch.watched_seconds, 0);
  assert.equal((await state()).progress, "started");
});

test("spoof: rewatching one part or interleaving two sessions does not add coverage", async () => {
  const { beat, state } = await setup();
  for (let round = 0; round < 4; round++) {
    await beat(0, { playing: false, after: 5 });
    await beat(0, { after: 5 });
    for (let p = 10; p <= 50; p += 10) await beat(p, { after: 5 });
  }
  assert.equal((await state()).watch.watched_seconds, 50, "the same 50 s counted once");
  // Two tabs playing different parts: their beats break each other's runs.
  await beat(100, { playing: false, after: 5 });
  await beat(100, { after: 5 });
  for (let i = 0; i < 6; i++) {
    await beat(110 + i * 10, { after: 5 });
    await beat(10 + i * 10, { after: 5 });
  }
  // Only the first 10 s of the second tab, before the first tab interfered, count.
  assert.equal((await state()).watch.watched_seconds, 60);
});

test("legitimate: normal speed with pauses, a seek back and a resume completes at 90%", async () => {
  const { beat, state } = await setup();
  await beat(0);
  for (let p = 5; p <= 100; p += 5) await beat(p, { after: 5 });
  await beat(102, { playing: false, after: 2 }); // pause
  await beat(102, { after: 600 }); // resume ten minutes later
  await beat(60, { playing: false, after: 3 }); // seek back: not credited (backwards)
  await beat(60, { after: 0.2 });
  for (let p = 65; p <= 180; p += 5) await beat(p, { after: 5 });
  let s = await state();
  assert.equal(s.watch.watched_seconds, 180);
  assert.equal(s.progress, "completed", "180 of 200 s is 90%");
});

test("legitimate: 2× speed completes; skipping a middle part does not", async () => {
  const { beat, state } = await setup();
  await beat(0);
  for (let p = 10; p <= 80; p += 10) await beat(p, { after: 5 });
  await beat(80, { playing: false, after: 0.5 });
  await beat(140, { playing: false, after: 1 }); // seek forward 60 s
  await beat(140, { after: 0.5 });
  for (let p = 150; p <= 200; p += 10) await beat(p, { after: 5 });
  let s = await state();
  assert.equal(s.watch.watched_seconds, 140);
  assert.equal(s.progress, "started", "the skipped minute is missing");
  // Going back for the skipped part completes it.
  await beat(80, { playing: false, after: 5 });
  await beat(80, { after: 1 });
  for (let p = 90; p <= 140; p += 10) await beat(p, { after: 5 });
  s = await state();
  assert.equal(s.watch.watched_seconds, 200);
  assert.equal(s.progress, "completed");
});

test("overlapping heartbeats never lose a credited span", async () => {
  const { env, beat, state } = await setup();
  const { recordWatchBeat } = await import("../../src/services/progress.js");
  await beat(0);
  await beat(10, { after: 5 });
  // Another heartbeat's write lands between this one's read and its write.
  const lesson = await env.DB.prepare("SELECT * FROM lessons WHERE id = ?").bind(LESSON).first();
  lesson.video = await env.DB.prepare("SELECT * FROM video_assets WHERE id = ?").bind(lesson.video_id).first();
  const user = await env.DB.prepare("SELECT user_id FROM video_watch WHERE lesson_id = ?").bind(LESSON).first();
  const w = await env.DB.prepare("SELECT last_beat_at FROM video_watch WHERE lesson_id = ?").bind(LESSON).first();
  await env.DB.prepare("UPDATE video_watch SET last_beat_at = ? WHERE lesson_id = ?").bind(new Date(Date.parse(w.last_beat_at) - 5000).toISOString(), LESSON).run();
  let injected = false;
  const orig = env.DB;
  const DB = new Proxy(orig, {
    get(t, prop) {
      if (prop !== "prepare") return typeof t[prop] === "function" ? t[prop].bind(t) : t[prop];
      return (sql) => {
        const st = t.prepare(sql);
        if (injected || !sql.trimStart().startsWith("UPDATE video_watch SET last_position")) return st;
        injected = true;
        const run = st.run.bind(st);
        const bind = st.bind.bind(st);
        st.bind = (...a) => {
          const b = bind(...a);
          const r2 = b.run.bind(b);
          b.run = async () => {
            await orig.prepare("UPDATE video_watch SET segments_json = '[[0,10],[150,160]]', watched_seconds = 20, beats = beats + 1 WHERE lesson_id = ?").bind(LESSON).run();
            return r2();
          };
          return b;
        };
        st.run = run;
        return st;
      };
    },
  });
  await recordWatchBeat({ ...env, DB }, user.user_id, lesson, { position: 20, playing: true, now: new Date().toISOString() });
  assert.ok(injected, "the race was exercised");
  const s = await state();
  assert.deepEqual(JSON.parse(s.watch.segments_json), [[0, 20], [150, 160]], "both writers' spans are kept");
  assert.equal(s.watch.watched_seconds, 30);
});

test("a delayed older heartbeat never replaces a newer anchor", async () => {
  const { env, beat, state } = await setup();
  const { recordWatchBeat } = await import("../../src/services/progress.js");
  await beat(0);
  await beat(10, { after: 5 });
  const before = await state();
  const lesson = await env.DB.prepare("SELECT * FROM lessons WHERE id = ?").bind(LESSON).first();
  lesson.video = await env.DB.prepare("SELECT * FROM video_assets WHERE id = ?").bind(lesson.video_id).first();
  // A pause sent earlier arrives after the newer playing heartbeat was stored.
  const stale = new Date(Date.parse(before.watch.last_beat_at) - 3000).toISOString();
  await recordWatchBeat(env, before.watch.user_id, lesson, { position: 4, playing: false, now: stale });
  const after = await state();
  assert.equal(after.watch.playing, 1, "still playing");
  assert.equal(after.watch.last_position, before.watch.last_position);
  assert.equal(after.watch.last_beat_at, before.watch.last_beat_at);
  assert.equal(after.watch.beats, before.watch.beats);
});
