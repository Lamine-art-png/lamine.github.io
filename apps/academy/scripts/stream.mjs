// Cloudflare Stream protection for Academy lesson videos, run by deploy.sh.
//   node scripts/stream.mjs protect --out DIR [--reviewed FILE]
//   node scripts/stream.mjs create-key --out DIR
//
// protect: maps the account's uploads to Course A1's fourteen lesson videos
// (by title, with the video number as tie-break), then for each mapped upload
// requires signed URLs, restricts embedding to the Academy hosts and removes
// downloadable renditions. It re-reads every setting from Stream and probes
// playback from outside: the bare video id and an expired token must be
// refused, a fresh signed token must play. It writes, for deploy.sh to apply:
//   DIR/evidence.sql   stream_protection rows (the publication gate reads them)
//   DIR/mapping.sql    video_assets → Stream uid and duration (status untouched:
//                      every video is still approved by a person in the admin)
//   DIR/captions.sql   Stream's machine captions as drafts for human review
//   DIR/customer-code  the account's playback subdomain code
// With --reviewed (rows of reviewed captions exported from D1), reviewed
// captions replace machine ones in Stream's player.
// Exits 1 if any mapped video is not verifiably protected. Logs carry titles
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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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

async function protect() {
  const out = arg("out");
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
  for (const v of unmapped) log(`- Upload "${v.meta?.name || "(untitled)"}" (\`${short(v.uid)}\`) matches no lesson video: protected like the others, not linked to a lesson`);

  const evidence = [];
  const mapping = [];
  const captions = [];
  // Failures are protection failures only; a missing upload is a content gap
  // (reported above, and enforced by the publication gate), not a leak.
  let failures = 0;
  let customer = "";
  const pendingCaptions = [];
  const reviewed = arg("reviewed") ? JSON.parse(readFileSync(arg("reviewed"), "utf8")) : [];
  log("");
  log("| # | Lesson video | Upload | Matched by | Id | State | Video length | Lesson est. | Signed | Origins | Downloads | Bare id (HLS / MP4 / thumb) | Fresh token | Expired token | Captions |");
  log("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|");
  // Every upload in the account is protected; mapped ones are also linked to their lesson.
  const rows = [...map, ...unmapped.map((v) => ({ upload: { uid: v.uid, name: v.meta?.name || "" }, video: null }))];
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
      const fresh = await cf(`/stream/${uid}/token`, { method: "POST", body: { exp: Math.floor(Date.now() / 1000) + 300, downloadable: false } });
      const signed = await anonymous(`${base}/${fresh.token}/manifest/video.m3u8`);
      // A token that has expired (valid for 2 s, used after 5 s) must be refused.
      const brief = await cf(`/stream/${uid}/token`, { method: "POST", body: { exp: Math.floor(Date.now() / 1000) + 2, downloadable: false } });
      await sleep(5000);
      const expired = await refused(`${base}/${brief.token}/manifest/video.m3u8`);
      const ok = v.requireSignedURLs === true && downloads === "none" && bare >= 400 && bareMp4 >= 400 && bareThumb >= 400 && expired >= 400 && signed === 200 && ORIGINS.every((o) => (v.allowedOrigins || []).includes(o));
      if (!ok) failures++;
      const duration = Math.round(v.duration || 0);
      // 4. Captions: Stream's machine captions become drafts for review;
      // reviewed captions from the Academy replace them in the player.
      let caps = (await cf(`/stream/${uid}/captions`)) || [];
      const mine = video && reviewed.find((r) => r.video_id === video.id && r.locale.split("-")[0] === "en");
      if (mine) {
        const current = caps.find((c) => c.language === "en");
        const live = current && !current.generated ? (await cf(`/stream/${uid}/captions/en/vtt`, { raw: true })).text : "";
        if (live.trim() !== mine.vtt.trim()) {
          // One caption per language: the machine draft makes way for the reviewed file.
          if (current) await cf(`/stream/${uid}/captions/en`, { method: "DELETE" });
          const fd = new FormData();
          fd.append("file", new Blob([mine.vtt], { type: "text/vtt" }), "en.vtt");
          await cf(`/stream/${uid}/captions/en`, { method: "PUT", body: fd });
        }
      } else if (!caps.some((c) => c.language === "en") && process.env.STREAM_GENERATE_CAPTIONS === "1" && v.readyToStream) {
        await cf(`/stream/${uid}/captions/en/generate`, { method: "POST" });
      }
      caps = (await cf(`/stream/${uid}/captions`)) || [];
      if (video && !mine) {
        const draft = await machineDraft(uid, video, caps);
        if (draft) captions.push(draft);
        else if (caps.some((c) => c.language === "en" && c.generated)) pendingCaptions.push({ uid, video });
      }
      const capDesc = caps.map((c) => `${c.language}${c.generated ? " (machine)" : ""}:${c.status || "ready"}`).join(" ") || "none";
      evidence.push(
        `INSERT OR REPLACE INTO stream_protection (uid, title, duration_seconds, signed_required, allowed_origins, downloads, anonymous_status, checked_at) VALUES (${[uid, upload.name, duration, v.requireSignedURLs ? 1 : 0, (v.allowedOrigins || []).join(" "), downloads, ok ? Math.min(bare, bareMp4, bareThumb, expired) : 200, new Date().toISOString()].map(sql).join(", ")});`,
      );
      if (video && v.readyToStream && duration > 0)
        mapping.push(
          `UPDATE video_assets SET provider = 'stream', provider_ref = ${sql(uid)}, duration_seconds = ${duration}, updated_at = ${sql(new Date().toISOString())} WHERE id = ${sql(video.id)} AND COALESCE(provider_ref, '') IN ('', ${sql(uid)}) AND (provider <> 'stream' OR COALESCE(provider_ref, '') <> ${sql(uid)} OR COALESCE(duration_seconds, 0) <> ${duration});`,
        );
      row = `| ${video ? video.n : "—"} | ${video ? video.title : "(no lesson)"} | ${upload.name.replace(/\|/g, "/")} | ${by || "—"} | \`${short(uid)}\` | ${v.status?.state || "?"} | ${Math.floor(duration / 60)}:${String(duration % 60).padStart(2, "0")} | ${video ? `${video.minutes} min` : "—"} | ${v.requireSignedURLs ? "yes" : "**NO**"} | ${(v.allowedOrigins || []).join(" ") || "**any**"} | ${downloads} | ${bare} / ${bareMp4} / ${bareThumb} | ${signed} | ${expired} | ${capDesc} |${ok ? " ✅" : " **NOT PROTECTED**"}`;
    } catch (e) {
      failures++;
      row = `| ${video ? video.n : "—"} | ${video ? video.title : "(no lesson)"} | ${upload.name} | ${by || "—"} | \`${short(uid)}\` | **error: ${String(e.message).slice(0, 120)}** |`;
    }
    log(row);
  }
  // Generation takes a few minutes; wait for drafts requested in this run.
  for (let i = 0; i < 30 && pendingCaptions.length; i++) {
    await sleep(10000);
    for (const p of [...pendingCaptions]) {
      const draft = await machineDraft(p.uid, p.video, (await cf(`/stream/${p.uid}/captions`)) || []);
      if (draft) {
        captions.push(draft);
        pendingCaptions.splice(pendingCaptions.indexOf(p), 1);
      }
    }
  }
  writeFileSync(join(out, "evidence.sql"), evidence.join("\n") + "\n");
  writeFileSync(join(out, "mapping.sql"), mapping.join("\n") + "\n");
  writeFileSync(join(out, "captions.sql"), captions.join("\n") + "\n");
  writeFileSync(join(out, "customer-code"), customer);
  log("");
  log(`- Bare id and expired token: HTTP status for a request without a valid token (must be 4xx). Fresh token: a 5-minute signed token (must be 200). Lesson est.: the lesson's displayed time, which includes reading the lesson text.`);
  log(`- Machine captions imported as **drafts awaiting human review** (status "machine", never shown to learners): ${captions.length}`);
  if (pendingCaptions.length) log(`- Captions still generating (imported by the next deploy): ${pendingCaptions.map((p) => p.video.n).join(", ")}`);
  log(failures ? `- **${failures} upload(s) not verifiably protected.**` : `- All ${rows.length} uploads verified private (${map.length} linked to lesson videos).`);
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, lines.join("\n") + "\n");
  process.exit(failures ? 1 : 0);
}

/**
 * SQL importing Stream's finished machine captions for a lesson video as a
 * draft. A caption a person has marked reviewed is never overwritten.
 */
async function machineDraft(uid, video, caps) {
  const machine = caps.find((c) => c.language === "en" && c.generated && (c.status || "ready") === "ready");
  if (!machine) return null;
  const vtt = (await cf(`/stream/${uid}/captions/en/vtt`, { raw: true })).text;
  if (!vtt.startsWith("WEBVTT")) return null;
  return `INSERT INTO video_captions (id, video_id, locale, label, vtt, status, created_at) VALUES (${sql(`cap_${video.id.slice(4)}_en`)}, ${sql(video.id)}, 'en', 'English', ${sql(vtt)}, 'machine', ${sql(new Date().toISOString())}) ON CONFLICT(video_id, locale) DO UPDATE SET vtt = excluded.vtt WHERE video_captions.status = 'machine' AND video_captions.vtt <> excluded.vtt;`;
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
  if (cmd === "protect") await protect();
  else if (cmd === "create-key") await createKey();
  else {
    console.error("usage: stream.mjs protect --out DIR [--reviewed FILE] | create-key --out DIR");
    process.exit(2);
  }
}
