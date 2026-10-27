// The caption reflow (scripts/caption-reflow.mjs) changes layout and timing
// only: same words in the same order, no overlap, nothing past the video,
// every draft cue's speech still covered. The deploy applies it once per
// unreviewed draft, keeps the original, and never touches reviewed captions,
// a reviewer's edits or a released video.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { reflow, reflowAll, parse, wrap, DRAFTS_SQL } from "../../scripts/caption-reflow.mjs";
import { captionQa, LIMITS } from "../../scripts/caption-qa.mjs";
import { A1 } from "../../src/content/courses/a1.js";
import { makeEnv, registeredLearner, publishCourse } from "../helpers.js";

const words = (vtt) => parse(vtt).cues.flatMap((c) => c.text.split(/\s+/).filter(Boolean));
const ts = (ms) => new Date(ms).toISOString().slice(11, 23);

/**
 * A draft shaped like Stream's speech recognition output: one long line per
 * cue, cues back to back at the presenter's pace, a few sub-second fragments
 * and a few cues too long for two lines.
 */
function streamLikeDraft(text, { wps = 2.6, seed = 7 } = {}) {
  const toks = text.replace(/\s+/g, " ").trim().split(" ");
  let rnd = seed;
  const next = () => (rnd = (rnd * 48271) % 2147483647) / 2147483647;
  const cues = [];
  let t = 0;
  for (let i = 0; i < toks.length; ) {
    const r = next();
    const n = r < 0.12 ? 1 : r < 0.25 ? 22 : 8 + Math.floor(next() * 5);
    const part = toks.slice(i, i + n);
    const dur = Math.round((part.length / wps) * 1000);
    const pause = next() < 0.3 ? 400 : 0;
    cues.push(`${ts(t)} --> ${ts(t + dur)}\n${part.join(" ")}`);
    t += dur + pause;
    i += n;
  }
  return { vtt: `WEBVTT\n\n${cues.join("\n\n")}\n`, durationMs: t + 1500 };
}

const scripts = A1.modules.flatMap((m) => m.lessons).filter((l) => l.script).map((l) => l.script.replace(/[#*>]/g, ""));

test("reflow keeps every word, in order, and fixes line length and short cues", () => {
  assert.ok(scripts.length >= 10, "A1 narration scripts as realistic speech");
  let before = { long: 0, short: 0 };
  let after = { long: 0, short: 0 };
  scripts.forEach((s, i) => {
    const { vtt, durationMs } = streamLikeDraft(s, { seed: 11 + i });
    const r = reflow(vtt, durationMs);
    assert.deepEqual(words(r.vtt), words(vtt), "same words in the same order");
    const qb = captionQa(vtt, durationMs / 1000).counts;
    const qa = captionQa(r.vtt, durationMs / 1000).counts;
    before.long += qb.long;
    before.short += qb.short;
    after.long += qa.long;
    after.short += qa.short;
    assert.equal(qa.long, 0, "no line over 42 characters");
    assert.equal(qa.tall, 0, "at most two lines");
    assert.equal(qa.overlaps, 0, "no overlapping cues");
    assert.ok(qa.fast <= qb.fast + r.estimated, "reading speed never made worse except by splitting a fast cue");
  });
  assert.ok(before.long > 50 && before.short > 5, "the fixture has the defects seen in production");
  assert.ok(after.short < before.short / 2, `short cues ${before.short} → ${after.short}`);
});

test("timing: no cue starts before its speech, the draft's speech stays covered, nothing runs past the video", () => {
  const { vtt, durationMs } = streamLikeDraft(scripts[0], { seed: 3 });
  const orig = parse(vtt).cues;
  const out = parse(reflow(vtt, durationMs).vtt).cues;
  assert.ok(out.every((c, i) => c.start < c.end && (i === 0 || c.start >= out[i - 1].end)), "ordered, no overlap");
  assert.ok(out.at(-1).end <= durationMs);
  for (const o of orig) {
    assert.ok(out.some((c) => c.start <= o.start && c.end > o.start), "a cue is on screen when each draft cue's speech starts");
    assert.ok(out.some((c) => c.start < o.end && c.end >= o.end), "and when it ends");
  }
});

test("a short fragment joins its neighbour and a sentence too long for two lines is split at punctuation", () => {
  const vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nIrrigation scheduling uses evapotranspiration data\n\n00:00:03.000 --> 00:00:03.500\ndaily.\n\n00:00:04.000 --> 00:00:11.000\nKc adjusts reference evapotranspiration for the crop, and the result guides how much water to apply each week.\n";
  const r = reflow(vtt, 12000);
  const cues = parse(r.vtt).cues;
  assert.equal(cues[0].text, "Irrigation scheduling uses evapotranspiration data daily.");
  assert.equal(cues[1].text, "Kc adjusts reference evapotranspiration for the crop,", "split after the comma");
  assert.equal(r.estimated, 2, "the split cues are counted as estimated timing for the reviewer");
  assert.match(r.vtt, /00:00:00\.000 --> 00:00:03\.500\nIrrigation scheduling uses\nevapotranspiration data daily\./);
  assert.ok(wrap("Kc adjusts reference evapotranspiration for the crop,").length === 2);
});

test("a draft whose cues already overlap is refused and nothing is written", () => {
  const good = { id: "cap_a", video_id: "vid_a", vtt: "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nA short line of speech here today friends.", duration: 5 };
  const bad = { id: "cap_b", video_id: "vid_b", vtt: "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nFirst words\n\n00:00:02.000 --> 00:00:04.000\nsecond words", duration: 5 };
  assert.throws(() => reflowAll([good, bad]), /nothing written[\s\S]*vid_b: cue 2 overlaps/);
  assert.equal(reflowAll([good]).sql.length, 1);
});

test("the report shows counts and never caption text", () => {
  const { vtt, durationMs } = streamLikeDraft(scripts[1]);
  const { report } = reflowAll([{ id: "cap_x", video_id: "vid_x", vtt, duration: durationMs / 1000 }]);
  assert.match(report, /\| vid_x \| \d+ \| \d+/);
  for (const w of words(vtt).filter((w) => w.length > 6).slice(0, 20)) assert.ok(!report.includes(w), `caption word "${w}" in the report`);
});

// ── Applied to a database, as the deploy does ──

const draftRows = async (env) => (await env.DB.prepare(DRAFTS_SQL).all()).results;
async function applyReflow(env) {
  const { sql } = reflowAll(await draftRows(env), "2026-10-27T20:00:00.000Z");
  for (const s of sql) await env.DB.prepare(s).run();
  return sql.length;
}
async function withDrafts() {
  const env = makeEnv();
  const now = new Date().toISOString();
  const a = streamLikeDraft(scripts[2], { seed: 5 });
  const b = streamLikeDraft(scripts[3], { seed: 9 });
  await env.DB.prepare("UPDATE video_assets SET duration_seconds = ? WHERE id = 'vid_a1_data'").bind(Math.ceil(a.durationMs / 1000)).run();
  await env.DB.prepare("INSERT INTO video_captions (id, video_id, locale, label, vtt, status, created_at) VALUES ('cap_data_en','vid_a1_data','en','English',?,'machine',?), ('cap_models_en','vid_a1_models','en','English',?,'reviewed',?)")
    .bind(a.vtt, now, b.vtt, now)
    .run();
  return { env, draft: a.vtt, reviewed: b.vtt };
}
const caption = (env, id) => env.DB.prepare("SELECT vtt, source_vtt, status, reflowed_at FROM video_captions WHERE id = ?").bind(id).first();

test("the deploy reflows each unreviewed draft once, keeps the original, and it stays an unreviewed draft", async () => {
  const { env, draft, reviewed } = await withDrafts();
  assert.equal(await applyReflow(env), 1, "only the machine draft");
  const c = await caption(env, "cap_data_en");
  assert.equal(c.status, "machine", "still an unreviewed draft");
  assert.equal(c.source_vtt, draft, "the original draft is kept");
  assert.notEqual(c.vtt, draft);
  assert.deepEqual(words(c.vtt), words(draft));
  assert.equal(c.reflowed_at, "2026-10-27T20:00:00.000Z");
  assert.equal((await caption(env, "cap_models_en")).vtt, reviewed, "a reviewed caption is never touched");
  // A reviewer's later edit of the draft is never overwritten by the next deploy.
  await env.DB.prepare("UPDATE video_captions SET vtt = 'WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nReviewer edit.' WHERE id = 'cap_data_en'").run();
  assert.equal(await applyReflow(env), 0);
  assert.match((await caption(env, "cap_data_en")).vtt, /Reviewer edit/);
});

test("the reflow write is guarded: a draft edited since it was read, or a released video, is left alone", async () => {
  const { env } = await withDrafts();
  const { sql } = reflowAll(await draftRows(env));
  await env.DB.prepare("UPDATE video_captions SET vtt = vtt || '\n' WHERE id = 'cap_data_en'").run();
  await env.DB.prepare(sql[0]).run();
  assert.equal((await caption(env, "cap_data_en")).source_vtt, null, "edited after it was read: not overwritten");

  const released = await withDrafts();
  const write = reflowAll(await draftRows(released.env)).sql;
  await publishCourse(released.env, "crs_a1");
  await released.env.DB.prepare(write[0]).run();
  assert.equal((await caption(released.env, "cap_data_en")).source_vtt, null, "a released video's captions change only through a new revision");
});

test("staff can open the original draft; learners never see a draft or an original", async () => {
  const { env, draft } = await withDrafts();
  await applyReflow(env);
  const admin = await registeredLearner(env, { email: "admin-reflow@academy.test" });
  const uid = (await env.DB.prepare("SELECT id FROM users WHERE email = 'admin-reflow@academy.test'").first()).id;
  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, 'academy_admin', ?)").bind(uid, new Date().toISOString()).run();
  let r = await admin.get("/captions/cap_data_en.source.vtt");
  assert.equal(r.status, 200);
  assert.equal(r.text, draft);
  r = await admin.get("/admin/videos/vid_a1_data");
  assert.match(r.text, /href="\/captions\/cap_data_en\.source\.vtt"/);
  assert.match(r.text, /reflowed for readability \(the words are unchanged; the original draft is kept\)/);
  const learner = await registeredLearner(env);
  for (const path of ["/captions/cap_data_en.vtt", "/captions/cap_data_en.source.vtt", "/captions/cap_models_en.source.vtt"]) assert.equal((await learner.get(path)).status, 404, path);
});

test("rolling back migration 0012 restores the original drafts and leaves reviewed captions alone", async () => {
  const { env, draft, reviewed } = await withDrafts();
  await applyReflow(env);
  const down = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../../migrations/down/0012_caption_source.down.sql"), "utf8");
  await env.DB.exec(down);
  assert.equal((await env.DB.prepare("SELECT vtt FROM video_captions WHERE id = 'cap_data_en'").first()).vtt, draft);
  assert.equal((await env.DB.prepare("SELECT vtt FROM video_captions WHERE id = 'cap_models_en'").first()).vtt, reviewed);
});

test("limits are the caption QA limits", () => {
  assert.equal(LIMITS.lineChars, 42);
  assert.equal(wrap("x".repeat(43)), null, "a single overlong word cannot be wrapped");
});
