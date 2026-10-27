// Cloudflare Stream protection for Academy lesson videos, run by deploy.sh.
//   node scripts/stream.mjs protect --out DIR --caption-mode writer|readonly [--captions FILE]
//   node scripts/stream.mjs create-key --out DIR
//
// The Stream account is reserved for the Academy (founder policy, 2026-10-27).
// protect: maps the account's uploads to Course A1's fourteen lesson videos
// (by video number, with the title as fallback). An upload that maps to no
// lesson video is unexpected: it is reported, never modified, and the run
// fails. For each mapped upload it requires signed URLs, restricts embedding
// to the Academy hosts and removes downloadable renditions. It re-reads every
// setting from Stream and probes playback from outside: the bare video id and
// an expired token must be refused, a fresh signed token must play. It writes,
// for deploy.sh to apply:
//   DIR/evidence.sql   stream_protection rows (the publication gate reads them)
//   DIR/mapping.sql    video_assets → Stream uid and duration (status untouched:
//                      every video is still approved by a person in the admin)
//   DIR/captions.sql   Stream's machine captions as drafts for human review
//   DIR/customer-code  the account's playback subdomain code
// Captions: the uploads are shared by staging and production, so production
// is their only caption writer (--caption-mode writer): Stream's player is
// reconciled to production's reviewed captions (see syncCaptions). Staging
// (readonly) never uploads, deletes or generates a Stream caption track.
// Released course media is never changed.
// Exits 1 if any upload is not verifiably protected. Logs carry titles
// and shortened ids only; tokens and keys are never printed.
//
// create-key: creates a Stream signing key and writes DIR/key-id and
// DIR/key-jwk (mode 600) for `wrangler secret put`; deploy.sh deletes them.
//
// Requires STREAM_API_TOKEN (account token with Stream:Edit) and
// CLOUDFLARE_ACCOUNT_ID. STREAM_GENERATE_CAPTIONS=1 also asks Stream (included
// at no additional cost for Stream customers) to
// generate English captions for videos that have none.
import { writeFileSync, readFileSync, mkdirSync, appendFileSync } from "node:fs";
import { join } from "node:path";
import { A1 as a1 } from "../src/content/courses/a1.js";

const API = process.env.CF_API_BASE || "https://api.cloudflare.com/client/v4";
const ACCOUNT = process.env.CLOUDFLARE_ACCOUNT_ID || "";
const TOKEN = process.env.STREAM_API_TOKEN || "";
export const ORIGINS = ["academy.agroai-pilot.com", "academy-staging.agroai-pilot.com"];

const [cmd, ...rest] = process.argv.slice(2);
const arg = (name) => {
  const i = rest.indexOf(`--${name}`);
  return i >= 0 ? rest[i + 1] : null;
};
const lines = [];
const log = (s = "") => {
  console.log(s);
  lines.push(s);
};
const short = (uid) => `${String(uid).slice(0, 6)}…`;
const sql = (v) => (v == null ? "NULL" : typeof v === "number" ? String(v) : `'${String(v).replace(/'/g, "''")}'`);
// Time source for the playback probes, replaceable in tests to simulate a slow API.
export const clock = { now: () => Date.now(), sleep: (ms) => new Promise((r) => setTimeout(r, ms)) };
const sleep = (ms) => clock.sleep(ms);

async function cf(path, { method = "GET", body, raw = false } = {}) {
  const headers = { Authorization: `Bearer ${TOKEN}` };
  if (body && !(body instanceof FormData)) headers["Content-Type"] = "application/json";
  const r = await fetch(`${API}/accounts/${ACCOUNT}${path}`, { method, headers, body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined });
  if (raw) return { status: r.status, text: await r.text() };
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.success === false) throw new Error(`${method} ${path.replace(/[0-9a-f]{32}/g, (u) => short(u))}: HTTP ${r.status} ${(j.errors || []).map((e) => e.code).join(",")}`);
  return j.result;
}

async function anonymous(url) {
  for (let i = 0; i < 3; i++) {
    try {
      const r = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(15000) });
      return r.status;
    } catch {
      await sleep(2000);
    }
  }
  return 0;
}

/**
 * Status for a request that must be refused. A setting change can take a
 * moment to reach every edge, so a 200 is re-checked for up to a minute
 * before it is reported.
 */
async function refused(url) {
  let status = await anonymous(url);
  for (let i = 0; i < 6 && (status === 200 || status === 0); i++) {
    await sleep(10000);
    status = await anonymous(url);
  }
  return status;
}

/** Course A1's lesson videos in order: video number, asset id, lesson title. */
export function a1Videos(course = a1) {
  const out = [];
  for (const m of course.modules) for (const l of m.lessons) if (l.type !== "quiz") out.push({ n: out.length + 1, id: `vid_${l.id.replace(/^les_/, "")}`, title: l.title, minutes: l.minutes });
  return out;
}

const words = (s) =>
  String(s)
    .toLowerCase()
    .replace(/\.(mp4|mov|m4v|webm|mkv)$/i, "")
    .replace(/[^a-z0-9]+/g, " ")
    .split(" ")
    .filter((w) => w.length > 2 && !["the", "and", "case", "study", "lesson", "video", "final", "agro", "academy"].includes(w));

/**
 * Video number the founder wrote in an upload's name: leading ("Video3-",
 * "video 11-", "01 - ", "A1-07") or labelled ("Lesson 12"). Years and other
 * numbers are ignored; only 1-14 count.
 */
export function numberIn(name) {
  const s = String(name);
  const m = /^\s*(?:a1[\s_-]*)?(?:video|lesson|vid|v)?[\s_#-]*0?(\d{1,2})(?!\d)/i.exec(s) || /\b(?:video|lesson)[\s_#-]*0?(\d{1,2})(?!\d)/i.exec(s);
  const n = m ? Number(m[1]) : null;
  return n >= 1 && n <= 14 ? n : null;
}

const overlapOf = (name, title) => {
  const uw = new Set(words(name));
  const vw = words(title);
  return vw.filter((w) => uw.has(w)).length / Math.max(1, vw.length);
};

/**
 * Map uploads to lesson videos. The video number in the upload's name decides
 * when exactly one upload carries it (the final titles were reworded, so they
 * often share few words with the lesson titles). Uploads without a usable
 * number fall back to title overlap (at least half the lesson title's words,
 * unambiguous). Each upload and lesson video is used once.
 */
export function mapUploads(uploads, videos = a1Videos()) {
  const map = [];
  const usedU = new Set();
  const usedV = new Set();
  const take = (u, v, by) => {
    usedU.add(u.uid);
    usedV.add(v.id);
    map.push({ upload: u, video: v, by, overlap: overlapOf(u.name, v.title) });
  };
  for (const v of videos) {
    const withNumber = uploads.filter((u) => numberIn(u.name) === v.n);
    if (withNumber.length === 1) take(withNumber[0], v, "number");
  }
  const scored = [];
  for (const u of uploads.filter((x) => !usedU.has(x.uid) && numberIn(x.name) == null)) {
    for (const v of videos.filter((x) => !usedV.has(x.id))) {
      const overlap = overlapOf(u.name, v.title);
      if (overlap >= 0.5) scored.push({ u, v, overlap });
    }
  }
  scored.sort((a, b) => b.overlap - a.overlap);
  for (const s of scored) {
    if (usedU.has(s.u.uid) || usedV.has(s.v.id)) continue;
    if (scored.some((o) => o !== s && o.v.id === s.v.id && !usedU.has(o.u.uid) && o.overlap === s.overlap)) continue;
    take(s.u, s.v, "title");
  }
  return map.sort((a, b) => a.video.n - b.video.n);
}

/** Lesson numbers carried by more than one upload (a duplicate to resolve by hand). */
export function duplicateNumbers(uploads) {
  const counts = new Map();
  for (const u of uploads) {
    const n = numberIn(u.name);
    if (n) counts.set(n, (counts.get(n) || 0) + 1);
  }
  return [...counts].filter(([, c]) => c > 1).map(([n]) => n);
}

/**
 * Signed token that has expired by the time it is used; returns the status a
 * stranger gets with it (must be refused). The token is issued with 15 s of
 * headroom, so a slow API call never reaches Stream with its expiry already
 * past (Stream rejects that as invalid), and it is used 5 s after it expires.
 */
export async function expiredTokenStatus(uid, base) {
  let brief;
  let exp;
  for (let attempt = 1; ; attempt++) {
    exp = Math.floor(clock.now() / 1000) + 15;
    try {
      brief = await cf(`/stream/${uid}/token`, { method: "POST", body: { exp, downloadable: false } });
      break;
    } catch (e) {
      if (attempt >= 2) throw e;
    }
  }
  await sleep(Math.max(0, (exp + 5) * 1000 - clock.now()));
  return refused(`${base}/${brief.token}/manifest/video.m3u8`);
}

export async function protect({ out, captionsFile = null, captionMode = "readonly" }) {
  const writer = captionMode === "writer";
  if (writer && !captionsFile) throw new Error("caption writer mode needs --captions (the reviewed caption set)");
  mkdirSync(out, { recursive: true });
  const all = (await cf("/stream?limit=1000")) || [];
  const uploads = all.map((v) => ({ uid: v.uid, name: v.meta?.name || "" }));
  const map = mapUploads(uploads);
  const videos = a1Videos();
  log(`### Cloudflare Stream: ${all.length} upload(s) in the account, ${map.length} of ${videos.length} A1 lesson videos mapped`);
  const unmapped = all.filter((v) => !map.some((m) => m.upload.uid === v.uid));
  const missing = videos.filter((v) => !map.some((m) => m.video.id === v.id));
  for (const v of missing) log(`- **Lesson video ${v.n} (${v.title}): no upload found** — learners see "video in production" and publication stays blocked until it is uploaded and approved`);
  for (const n of duplicateNumbers(uploads)) log(`- **Several uploads are numbered ${n}**: none was mapped to lesson video ${n}; delete or rename the extra one`);
  for (const v of unmapped) log(`- **Unexpected upload "${String(v.meta?.name || "(untitled)").replace(/\|/g, "/")}" (\`${short(v.uid)}\`, created ${v.created || "?"})**: it maps to no A1 lesson video. This Stream account is reserved for the Academy, so it was left untouched and the deployment stops. Rename it to its lesson video number, or move it to another account.`);
  log(`- Caption mode: ${writer ? "writer (production): Stream's caption tracks are reconciled to production's reviewed captions" : "read-only (staging): Stream caption tracks are listed, never changed"}`);

  const evidence = [];
  const mapping = [];
  const captions = [];
  // Failures: an unexpected upload, a protection that cannot be verified, or
  // (writer) a caption track that is not exactly a reviewed caption. A missing
  // upload is a content gap (reported above, enforced by the publication
  // gate), not a leak.
  let failures = unmapped.length;
  let customer = "";
  const pendingCaptions = [];
  // Every caption the Academy holds (vtt only for reviewed ones), from D1.
  const known = captionsFile ? JSON.parse(readFileSync(captionsFile, "utf8")) : [];
  log("");
  log("| # | Lesson video | Upload | Matched by | Id | State | Video length | Lesson est. | Signed | Origins | Downloads | Bare id (HLS / MP4 / thumb) | Fresh token | Expired token | Captions |");
  log("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|");
  // Only the uploads mapped to A1 lesson videos are touched.
  const rows = map;
  for (const { upload, video, by } of rows) {
    const uid = upload.uid;
    let row;
    try {
      // 1. Protect: signed URLs only, Academy hosts only, no downloads.
      const before = await cf(`/stream/${uid}`);
      // meta is sent back unchanged so the upload keeps its name.
      await cf(`/stream/${uid}`, { method: "POST", body: { uid, meta: before.meta || {}, requireSignedURLs: true, allowedOrigins: ORIGINS } });
      const dl = await cf(`/stream/${uid}/downloads`);
      if (dl && Object.keys(dl).length) await cf(`/stream/${uid}/downloads`, { method: "DELETE" });
      // 2. Re-read what Stream actually holds.
      const v = await cf(`/stream/${uid}`);
      const downloads = Object.entries((await cf(`/stream/${uid}/downloads`)) || {}).map(([k, d]) => `${k}:${d.status}`).join(" ") || "none";
      const hls = v.playback?.hls || "";
      customer ||= /^https:\/\/customer-([a-z0-9]+)\.cloudflarestream\.com\//.exec(hls)?.[1] || "";
      const base = hls.replace(/\/[0-9a-f]{32}\/manifest\/video\.m3u8$/, "");
      // 3. Probe from outside, as a stranger would.
      const bare = await refused(hls);
      const bareMp4 = await refused(`${base}/${uid}/downloads/default.mp4`);
      const bareThumb = await refused(`${base}/${uid}/thumbnails/thumbnail.jpg`);
      const fresh = await cf(`/stream/${uid}/token`, { method: "POST", body: { exp: Math.floor(clock.now() / 1000) + 300, downloadable: false } });
      const signed = await anonymous(`${base}/${fresh.token}/manifest/video.m3u8`);
      const expired = await expiredTokenStatus(uid, base);
      const ok = v.requireSignedURLs === true && downloads === "none" && bare >= 400 && bareMp4 >= 400 && bareThumb >= 400 && expired >= 400 && signed === 200 && ORIGINS.every((o) => (v.allowedOrigins || []).includes(o));
      if (!ok) failures++;
      const duration = Math.round(v.duration || 0);
      evidence.push(evidenceRow(uid, upload.name, duration, v, downloads, ok ? Math.min(bare, bareMp4, bareThumb, expired) : 200));
      // 4. Captions. For the writer, a track that is not exactly a reviewed
      // caption (or a sync error) fails the run: it could be shown to learners.
      let capDesc;
      try {
        const sync = await syncCaptions(uid, video, v, known.filter((k) => video && k.video_id === video.id), captions, pendingCaptions, { writer });
        capDesc = sync.desc + (sync.problems.length ? ` **${sync.problems.join("; ")}**` : "");
        if (sync.problems.length) failures++;
      } catch (e) {
        capDesc = `**caption sync error: ${String(e.message).slice(0, 80)}**`;
        if (writer) failures++;
      }
      if (video && v.readyToStream && duration > 0)
        mapping.push(
          `UPDATE video_assets SET provider = 'stream', provider_ref = ${sql(uid)}, duration_seconds = ${duration}, updated_at = ${sql(new Date().toISOString())} WHERE id = ${sql(video.id)} AND COALESCE(provider_ref, '') IN ('', ${sql(uid)}) AND (provider <> 'stream' OR COALESCE(provider_ref, '') <> ${sql(uid)} OR COALESCE(duration_seconds, 0) <> ${duration}) AND NOT ${RELEASED("video_assets.id")};`,
        );
      row = `| ${video ? video.n : "—"} | ${video ? video.title : "(no lesson)"} | ${upload.name.replace(/\|/g, "/")} | ${by || "—"} | \`${short(uid)}\` | ${v.status?.state || "?"} | ${Math.floor(duration / 60)}:${String(duration % 60).padStart(2, "0")} | ${video ? `${video.minutes} min` : "—"} | ${v.requireSignedURLs ? "yes" : "**NO**"} | ${(v.allowedOrigins || []).join(" ") || "**any**"} | ${downloads} | ${bare} / ${bareMp4} / ${bareThumb} | ${signed} | ${expired} | ${capDesc} |${ok ? " ✅" : " **NOT PROTECTED**"}`;
    } catch (e) {
      failures++;
      // A check that could not complete replaces any earlier passing record with a failing one.
      evidence.push(evidenceRow(uid, upload.name, null, { requireSignedURLs: false, allowedOrigins: [] }, "unknown", 200));
      row = `| ${video ? video.n : "—"} | ${video ? video.title : "(no lesson)"} | ${upload.name} | ${by || "—"} | \`${short(uid)}\` | **error: ${String(e.message).slice(0, 120)}** |`;
    }
    log(row);
  }
  // Generation takes a few minutes; wait for drafts requested in this run.
  for (let i = 0; i < 30 && pendingCaptions.length; i++) {
    await sleep(10000);
    for (const p of [...pendingCaptions]) {
      const machine = ((await cf(`/stream/${p.uid}/captions`)) || []).find((c) => c.language === "en" && c.generated);
      if (!machine || (machine.status || "ready") !== "ready") continue;
      if (await importDraft(p.uid, p.video, captions)) pendingCaptions.splice(pendingCaptions.indexOf(p), 1);
    }
  }
  // A machine caption that did not finish in time is removed rather than left
  // to become playable unreviewed; the next production deploy requests it again.
  for (const p of pendingCaptions) {
    await cf(`/stream/${p.uid}/captions/en`, { method: "DELETE" });
    log(`- Lesson video ${p.video.n}: machine caption still generating; removed from Stream, requested again by the next production deploy`);
  }
  writeFileSync(join(out, "evidence.sql"), evidence.join("\n") + "\n");
  writeFileSync(join(out, "mapping.sql"), mapping.join("\n") + "\n");
  writeFileSync(join(out, "captions.sql"), captions.join("\n") + "\n");
  writeFileSync(join(out, "customer-code"), customer);
  log("");
  log(`- Bare id and expired token: HTTP status for a request without a valid token (must be 4xx). Fresh token: a 5-minute signed token (must be 200). Lesson est.: the lesson's displayed time, which includes reading the lesson text.`);
  log(`- Machine captions imported as **drafts awaiting human review** (status "machine"; removed from Stream's player, never shown to learners): ${captions.length}`);
  log(
    failures
      ? `- **${failures} problem(s): unexpected upload(s), upload(s) not verifiably protected, or caption tracks not reviewed.**`
      : `- All ${rows.length} uploads verified private (${map.length} linked to lesson videos); no unexpected uploads.`,
  );
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, lines.join("\n") + "\n");
  return failures ? 1 : 0;
}

// Released course media is immutable (as in the admin): the pipeline never
// changes a video record or caption used by a published course.
const RELEASED = (idExpr) =>
  `EXISTS (SELECT 1 FROM lessons l JOIN courses c ON c.id = l.course_id WHERE l.video_id = ${idExpr} AND c.published_at IS NOT NULL AND l.slug NOT LIKE '\\_\\_rev\\_%' ESCAPE '\\')`;

const evidenceRow = (uid, title, duration, v, downloads, anonymousStatus) =>
  `INSERT OR REPLACE INTO stream_protection (uid, title, duration_seconds, signed_required, allowed_origins, downloads, anonymous_status, checked_at) VALUES (${[uid, title, duration, v.requireSignedURLs ? 1 : 0, (v.allowedOrigins || []).join(" "), downloads, anonymousStatus, new Date().toISOString()].map(sql).join(", ")});`;

const streamLang = (locale) => String(locale).split("-")[0].toLowerCase();

/**
 * Caption tracks in Stream's player for one shared upload.
 *
 * Read-only (staging): lists the tracks and changes nothing. Production owns
 * the tracks of the shared uploads; staging keeps its own drafts in its
 * database only.
 *
 * Writer (production): the player carries exactly production's reviewed
 * captions. In order:
 * - a finished English machine caption, when no reviewed English exists, is
 *   imported as an Academy draft and removed from Stream (one still
 *   generating is left in progress and removed at the end of the run if it
 *   has not finished);
 * - every other track, of any language, generated or uploaded, that is not a
 *   reviewed caption with identical text is deleted;
 * - reviewed captions missing from Stream are uploaded;
 * - for English with no caption row at all, Stream is asked to generate one
 *   (STREAM_GENERATE_CAPTIONS=1);
 * - the tracks are re-read: anything not exactly reviewed is a problem.
 * Two reviewed locales that Stream stores under the same language (pt-BR and
 * pt-PT) are ambiguous: neither is published and the run reports it.
 * Returns { desc, problems }.
 */
export async function syncCaptions(uid, video, v, rows, captions, pending, { writer = false } = {}) {
  const list = async () => (await cf(`/stream/${uid}/captions`)) || [];
  const describe = (caps) => caps.map((c) => `${c.language}${c.generated ? " (machine)" : ""}:${c.status || "ready"}`).join(" ") || "none (in player)";
  if (!writer) return { desc: `${describe(await list())} (read-only; production manages tracks)`, problems: [] };

  const problems = [];
  const approved = new Map();
  const ambiguous = new Set();
  for (const r of rows.filter((x) => x.status === "reviewed" && x.vtt)) {
    const lang = streamLang(r.locale);
    if (approved.has(lang)) ambiguous.add(lang);
    else approved.set(lang, r.vtt.trim());
  }
  for (const lang of ambiguous) {
    approved.delete(lang);
    problems.push(`several reviewed captions for "${lang}": none published`);
  }
  const vttOf = async (lang) => (await cf(`/stream/${uid}/captions/${lang}/vtt`, { raw: true })).text.trim();
  const inProgress = (c) => c.generated && c.language === "en" && (c.status || "ready") !== "ready";

  let caps = await list();
  let drafted = false;
  const machine = caps.find((c) => c.language === "en" && c.generated);
  if (machine && video && !approved.has("en")) {
    if ((machine.status || "ready") === "ready") {
      drafted = await importDraft(uid, video, captions);
      if (drafted) caps = await list();
    } else if (!pending.some((p) => p.uid === uid)) pending.push({ uid, video });
  }
  for (const c of caps) {
    if (inProgress(c) && !approved.has("en")) continue;
    const want = approved.get(c.language);
    if (want == null || c.generated || (await vttOf(c.language)) !== want) await cf(`/stream/${uid}/captions/${c.language}`, { method: "DELETE" });
  }
  caps = await list();
  for (const [lang, vtt] of approved) {
    if (caps.some((c) => c.language === lang)) continue;
    const fd = new FormData();
    fd.append("file", new Blob([vtt + "\n"], { type: "text/vtt" }), `${lang}.vtt`);
    await cf(`/stream/${uid}/captions/${lang}`, { method: "PUT", body: fd });
  }
  const hasEnglishRow = drafted || rows.some((r) => streamLang(r.locale) === "en");
  caps = await list();
  if (video && !hasEnglishRow && !caps.some((c) => c.language === "en") && process.env.STREAM_GENERATE_CAPTIONS === "1" && v.readyToStream) {
    await cf(`/stream/${uid}/captions/en/generate`, { method: "POST" });
    if (!pending.some((p) => p.uid === uid)) pending.push({ uid, video });
    caps = await list();
  }
  // Verify what Stream now serves.
  for (const c of caps) {
    if (inProgress(c) && !approved.has("en")) continue;
    const want = approved.get(c.language);
    if (want == null || c.generated) problems.push(`unreviewed ${c.language} track in the player`);
    else if ((await vttOf(c.language)) !== want) problems.push(`${c.language} track differs from the reviewed caption`);
  }
  for (const lang of approved.keys()) if (!caps.some((c) => c.language === lang)) problems.push(`reviewed ${lang} caption missing from the player`);
  return { desc: describe(caps), problems };
}

/** Import Stream's finished English machine caption as an Academy draft, then remove it from the player. */
async function importDraft(uid, video, captions) {
  const vtt = (await cf(`/stream/${uid}/captions/en/vtt`, { raw: true })).text;
  if (!vtt.startsWith("WEBVTT")) return false;
  captions.push(
    `INSERT INTO video_captions (id, video_id, locale, label, vtt, status, created_at) SELECT ${sql(`cap_${video.id.slice(4)}_en`)}, ${sql(video.id)}, 'en', 'English', ${sql(vtt)}, 'machine', ${sql(new Date().toISOString())} WHERE NOT ${RELEASED(sql(video.id))} ON CONFLICT(video_id, locale) DO UPDATE SET vtt = excluded.vtt WHERE video_captions.status = 'machine' AND video_captions.vtt <> excluded.vtt;`,
  );
  await cf(`/stream/${uid}/captions/en`, { method: "DELETE" });
  return true;
}

async function createKey() {
  const out = arg("out");
  mkdirSync(out, { recursive: true });
  const key = await cf("/stream/keys", { method: "POST" });
  writeFileSync(join(out, "key-id"), key.id, { mode: 0o600 });
  writeFileSync(join(out, "key-jwk"), key.jwk, { mode: 0o600 });
  console.log("Created a Stream signing key (stored only as Worker secrets).");
}

if (import.meta.url === `file://${process.argv[1]}`) {
  if (!TOKEN || !ACCOUNT) {
    console.error("STREAM_API_TOKEN and CLOUDFLARE_ACCOUNT_ID are required");
    process.exit(2);
  }
  if (cmd === "protect") {
    const mode = arg("caption-mode");
    if (!["writer", "readonly"].includes(mode)) {
      console.error("protect needs --caption-mode writer (production) or readonly (staging)");
      process.exit(2);
    }
    process.exit(await protect({ out: arg("out"), captionsFile: arg("captions"), captionMode: mode }));
  }
  else if (cmd === "create-key") await createKey();
  else {
    console.error("usage: stream.mjs protect --out DIR --caption-mode writer|readonly [--captions FILE] | create-key --out DIR");
    process.exit(2);
  }
}
