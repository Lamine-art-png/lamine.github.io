// Protected video: Stream uploads play only from short-lived tokens the Worker
// signs for an entitled learner. These tests attack the lesson page, the
// token endpoint, captions, transcripts and the publication gate.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv, Client, registeredLearner, publishCourse } from "../helpers.js";
import { playbackToken, TOKEN_TTL_SECONDS } from "../../src/services/stream.js";
import { publishReadiness } from "../../src/services/readiness.js";

const COURSE = "/courses/introduction-to-ai-in-agriculture";
const LESSON_URL = "/learn/introduction-to-ai-in-agriculture/data-the-raw-material";
const LESSON = "les_a1_data";
const UID = "0123456789abcdef0123456789abcdef";

const signing = (async () => {
  const pair = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
  const jwk = await crypto.subtle.exportKey("jwk", pair.privateKey);
  return { publicKey: pair.publicKey, kid: "testkid0123456789abcdef01234567", jwk: btoa(JSON.stringify(jwk)), d: jwk.d };
})();

async function setup({ configured = true, environment = "test" } = {}) {
  const key = await signing;
  const env = makeEnv({ ENVIRONMENT: environment, ...(configured ? { STREAM_SIGNING_KEY_ID: key.kid, STREAM_SIGNING_JWK: key.jwk, STREAM_CUSTOMER_CODE: "abc123testcode" } : {}) });
  await publishCourse(env, "crs_a1");
  await env.DB.prepare("UPDATE video_assets SET status='approved', provider='stream', provider_ref=?, duration_seconds=200, hls_url=NULL, mp4_url=NULL WHERE id='vid_a1_data'").bind(UID).run();
  const learner = await registeredLearner(env);
  await learner.post(`${COURSE}/enroll`, {});
  return { env, key, learner };
}

const decode = (part) => JSON.parse(Buffer.from(part, "base64url").toString());
const tokenIn = (text) => /cloudflarestream\.com\/([\w-]+\.[\w-]+\.[\w-]+)\/iframe/.exec(text)?.[1];

test("an enrolled learner gets Stream's player with a short-lived token signed by the Worker", async () => {
  const { env, key, learner } = await setup();
  const r = await learner.get(LESSON_URL);
  assert.equal(r.status, 200);
  const token = tokenIn(r.text);
  assert.ok(token, "the player iframe carries a signed token in place of the video id");
  const [h, p, s] = token.split(".");
  assert.deepEqual(decode(h), { alg: "RS256", kid: key.kid });
  const claims = decode(p);
  assert.equal(claims.sub, UID);
  assert.equal(claims.downloadable, false);
  assert.ok(claims.exp - Date.now() / 1000 <= TOKEN_TTL_SECONDS && claims.exp - Date.now() / 1000 > TOKEN_TTL_SECONDS - 60, "expires in about 20 minutes");
  const valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key.publicKey, Buffer.from(s, "base64url"), new TextEncoder().encode(`${h}.${p}`));
  assert.ok(valid, "signature verifies against the Stream signing key");
  // Nothing in the page plays without a token: no bare id, manifest, MP4 or key material.
  assert.ok(!r.text.includes(UID), "the bare video id never appears in the page");
  assert.doesNotMatch(r.text, /\.m3u8|\.mp4|\/downloads|\/manifest\//);
  assert.ok(!r.text.includes(key.d) && !r.text.includes(key.jwk), "no signing key material");
  assert.doesNotMatch(r.text, /<video/, "no direct media element for a Stream video");
  // A narrated text lesson completes by watching only: no manual completion is offered.
  assert.doesNotMatch(r.text, /data-complete-form/);
  // Private, unindexed, unframeable; the player SDK is allowed on this page only.
  assert.equal(r.headers.get("cache-control"), "private, no-store");
  assert.match(r.text, /<meta name="robots" content="noindex/);
  const csp = r.headers.get("content-security-policy");
  assert.match(csp, /script-src 'self' https:\/\/embed\.cloudflarestream\.com/);
  assert.match(csp, /frame-ancestors 'none'/);
  assert.equal(r.headers.get("x-frame-options"), "DENY");
  assert.equal(r.headers.get("x-academy-stream-player"), null, "the internal marker is stripped");
  const home = await learner.get("/dashboard");
  assert.match(home.headers.get("content-security-policy"), /script-src 'self';/, "other pages keep the strict script policy");
});

test("anonymous, unenrolled and withdrawn visitors get no lesson, token, captions or transcript", async () => {
  const { env, learner } = await setup();
  const anon = new Client(env);
  let r = await anon.get(LESSON_URL);
  assert.equal(r.status, 303);
  assert.match(r.location, /^\/login\?next=/);
  // Preview lessons are no exception for anonymous visitors.
  r = await anon.get("/learn/introduction-to-ai-in-agriculture/welcome");
  assert.equal(r.status, 303);
  assert.match(r.location, /^\/login/);
  const outsider = await registeredLearner(env);
  r = await outsider.get(LESSON_URL);
  assert.equal(r.status, 303);
  assert.equal(r.location, COURSE, "registration alone is not enrollment");
  r = await outsider.postJson("/api/video-token", { lessonId: LESSON });
  assert.equal(r.status, 403);
  assert.equal(r.text.includes("cloudflarestream"), false);
  // Withdrawal revokes access at once, including token renewal.
  r = await learner.postJson("/api/video-token", { lessonId: LESSON });
  assert.equal(r.status, 200);
  await env.DB.prepare("UPDATE enrollments SET status = 'withdrawn'").run();
  r = await learner.postJson("/api/video-token", { lessonId: LESSON });
  assert.equal(r.status, 403);
  r = await learner.get(LESSON_URL);
  assert.equal(r.status, 303);
  // Without a session the endpoint never issues a token.
  r = await anon.postJson("/api/video-token", { lessonId: LESSON });
  assert.notEqual(r.status, 200);
});

test("token renewal: entitled learners only, rate limited, never cached, fails closed without the key", async () => {
  const { learner } = await setup();
  let r = await learner.postJson("/api/video-token", { lessonId: LESSON });
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("cache-control"), "private, no-store");
  const body = JSON.parse(r.text);
  assert.ok(tokenIn(body.url));
  assert.ok(Date.parse(body.expiresAt) > Date.now());
  // A lesson without a Stream video, and an unknown lesson, issue nothing.
  r = await learner.postJson("/api/video-token", { lessonId: "les_a1_welcome" });
  assert.notEqual(r.status, 200);
  r = await learner.postJson("/api/video-token", { lessonId: "les_nope" });
  assert.equal(r.status, 403);
  // Scraping: tokens are rate limited per learner.
  let limited = false;
  for (let i = 0; i < 70 && !limited; i++) limited = (await learner.postJson("/api/video-token", { lessonId: LESSON })).status === 429;
  assert.ok(limited, "token issuance is rate limited");

  const off = await setup({ configured: false });
  r = await off.learner.get(LESSON_URL);
  assert.equal(r.status, 200);
  assert.doesNotMatch(r.text, /<iframe|cloudflarestream|videodelivery/, "no player without the signing key");
  assert.match(r.text, /This video is temporarily unavailable/);
  r = await off.learner.postJson("/api/video-token", { lessonId: LESSON });
  assert.equal(r.status, 503);
  // An unplayable video never strands the learner: the lesson completes from its text.
  r = await off.learner.post(LESSON_URL + "/complete", {});
  assert.doesNotMatch(r.location || "", /watch=1/);
  assert.equal((await off.env.DB.prepare("SELECT status FROM lesson_progress WHERE lesson_id = ?").bind(LESSON).first()).status, "completed");
});

test("a copied token is only as good as its expiry", async () => {
  const key = await signing;
  const env = { STREAM_SIGNING_KEY_ID: key.kid, STREAM_SIGNING_JWK: key.jwk };
  const at = Date.parse("2026-10-29T12:00:00Z");
  const { token, expiresAt } = await playbackToken(env, UID, { now: at });
  const claims = decode(token.split(".")[1]);
  assert.equal(claims.exp, at / 1000 + TOKEN_TTL_SECONDS);
  assert.equal(expiresAt, new Date(at + TOKEN_TTL_SECONDS * 1000).toISOString());
  assert.equal(await playbackToken(env, "not-a-uid"), null, "only well-formed Stream ids are signed");
  assert.equal(await playbackToken({}, UID), null, "no key, no token");
});

test("captions: reviewed only, enrolled only, private; the transcript comes from reviewed captions, never the script", async () => {
  const { env, learner } = await setup();
  const now = new Date().toISOString();
  await env.DB.prepare("UPDATE video_assets SET script_md = 'PLANNING SCRIPT TEXT' WHERE id = 'vid_a1_data'").run();
  await env.DB.prepare("INSERT INTO video_captions (id, video_id, locale, label, vtt, status, created_at) VALUES ('cap_en','vid_a1_data','en','English',?,'reviewed',?), ('cap_fr','vid_a1_data','fr-FR','Français','WEBVTT\n\n00:00.000 --> 00:02.000\nBrouillon','machine',?)")
    .bind("WEBVTT\n\n00:00.000 --> 00:04.000\nSoil moisture is <b>data</b>.\n\n00:04.000 --> 00:09.000\nFarmers record it daily.\n\n01:05.000 --> 01:09.000\nModels learn from it.", now, now)
    .run();
  let r = await learner.get(LESSON_URL);
  assert.match(r.text, /id="panel-transcript"/);
  assert.match(r.text, /data-seek="0">0:00<\/button> Soil moisture is data\. Farmers record it daily\./);
  assert.match(r.text, /data-seek="65">1:05<\/button> Models learn from it\./);
  assert.doesNotMatch(r.text, /PLANNING SCRIPT TEXT/, "the planning script is not the transcript");
  r = await learner.get("/captions/cap_en.vtt");
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("cache-control"), "private, no-store");
  r = await learner.get("/captions/cap_fr.vtt");
  assert.equal(r.status, 404, "unreviewed machine captions are not served to learners");
  const outsider = await registeredLearner(env);
  r = await outsider.get("/captions/cap_en.vtt");
  assert.equal(r.status, 404, "captions of a course the learner is not enrolled in");
  r = await new Client(env).get("/captions/cap_en.vtt");
  assert.notEqual(r.status, 200);
});

test("deployed Academies never play direct media URLs, which are public by nature", async () => {
  for (const environment of ["staging", "production"]) {
    const env = makeEnv({ ENVIRONMENT: environment });
    await publishCourse(env, "crs_a1");
    await env.DB.prepare("UPDATE video_assets SET status='approved', provider='r2', duration_seconds=200, mp4_url='https://media.example/a1.mp4', hls_url='https://media.example/a1.m3u8' WHERE id='vid_a1_data'").run();
    const learner = await registeredLearner(env);
    await learner.post(`${COURSE}/enroll`, {});
    const r = await learner.get(LESSON_URL);
    assert.doesNotMatch(r.text, /media\.example|<video/, environment);
  }
});

test("publication requires recent evidence that each Stream video is private", async () => {
  const { env } = await setup();
  const course = await env.DB.prepare("SELECT * FROM courses WHERE id = 'crs_a1'").first();
  const check = async () => (await publishReadiness(env, course)).checks.find((c) => /Stream/.test(c.label));
  let c = await check();
  assert.equal(c.ok, false);
  assert.match(c.label, /without verified Stream protection/);
  // Optional lessons are covered too: every Stream video learners can play needs evidence.
  await env.DB.prepare("UPDATE draft_lessons SET is_required = 0 WHERE id = ?").bind(LESSON).run();
  assert.equal((await check()).ok, false, "optional lesson video without evidence");
  await env.DB.prepare("UPDATE draft_lessons SET is_required = 1 WHERE id = ?").bind(LESSON).run();
  const record = (signed, anon, downloads, at = new Date().toISOString()) =>
    env.DB.prepare("INSERT OR REPLACE INTO stream_protection (uid, title, signed_required, downloads, anonymous_status, checked_at) VALUES (?, 'x', ?, ?, ?, ?)").bind(UID, signed, downloads, anon, at).run();
  await record(1, 200, "none");
  assert.equal((await check()).ok, false, "anonymous playback still answered");
  await record(1, 401, "default:ready");
  assert.equal((await check()).ok, false, "a downloadable rendition exists");
  await record(1, 401, "none", "2026-01-01T00:00:00Z");
  assert.equal((await check()).ok, false, "stale evidence");
  await record(1, 401, "none");
  assert.equal((await check()).ok, true);
});

test("lesson resources are for enrolled learners only, previews included", async () => {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT INTO lesson_resources (id, lesson_id, title, kind, url, sort_order, created_at) VALUES ('res1','les_a1_welcome','Guide','link','https://example.com/guide',0,?)").bind(now).run();
  const outsider = await registeredLearner(env);
  const r = await outsider.get("/resources/res1");
  assert.equal(r.status, 403);
});

test("a caption reviewer corrects Stream's machine draft in place; only the reviewed version reaches learners", async () => {
  const { env, learner } = await setup();
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT INTO video_captions (id, video_id, locale, label, vtt, status, created_at) VALUES ('cap_a1_data_en','vid_a1_data','en','English','WEBVTT\n\n00:00.000 --> 00:03.000\nsoil moister is data','machine',?)").bind(now).run();
  let r = await learner.get(LESSON_URL);
  assert.doesNotMatch(r.text, /soil moister/, "learners never see a machine draft");
  // Captions are corrected before publication: a released course's media is locked.
  await env.DB.prepare("UPDATE courses SET status = 'review', published_at = NULL WHERE id = 'crs_a1'").run();
  const admin = await registeredLearner(env, { email: "founder@academy.test" });
  r = await admin.get("/admin/videos/vid_a1_data");
  assert.match(r.text, /<textarea id="a-vtt" name="vtt" rows="20" class="code" required>WEBVTT\n\n00:00.000 --&gt; 00:03.000\nsoil moister is data<\/textarea>/);
  assert.match(r.text, /Machine draft from Stream loaded/);
  r = await admin.post("/admin/videos/vid_a1_data/captions", { locale: "en", status: "reviewed", vtt: "WEBVTT\n\n00:00.000 --> 00:03.000\nSoil moisture is data." });
  assert.equal(r.status, 303);
  const row = await env.DB.prepare("SELECT status, vtt FROM video_captions WHERE video_id = 'vid_a1_data' AND locale = 'en'").first();
  assert.equal(row.status, "reviewed");
  await publishCourse(env, "crs_a1");
  r = await learner.get(LESSON_URL);
  assert.match(r.text, /Soil moisture is data\./);
});
