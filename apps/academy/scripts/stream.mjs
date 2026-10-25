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
// CLOUDFLARE_ACCOUNT_ID. STREAM_GENERATE_CAPTIONS=1 also asks Stream to
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

/** Video number written in an upload's name ("01 Welcome", "A1-07", "Lesson 7 –"), if any. */
export function numberIn(name) {
  const m = /(?:^|[^0-9])(?:a1[\s_-]*)?(?:video|lesson|v)?[\s_#-]*0?([1-9]|1[0-4])(?:[^0-9]|$)/i.exec(String(name).replace(/\.(mp4|mov|m4v|webm)$/i, ""));
  return m ? Number(m[1]) : null;
}

/**
 * Map uploads to lesson videos: best title overlap (at least half the
 * lesson title's words), the video number breaking ties. Each upload and each
 * lesson video is used once; anything ambiguous is left unmapped.
 */
export function mapUploads(uploads, videos = a1Videos()) {
  const scored = [];
  for (const u of uploads) {
    const uw = new Set(words(u.name));
    const num = numberIn(u.name);
    for (const v of videos) {
      const vw = words(v.title);
      const overlap = vw.filter((w) => uw.has(w)).length / Math.max(1, vw.length);
      const score = overlap + (num === v.n ? 0.25 : 0);
      if (overlap >= 0.5 || (num === v.n && overlap >= 0.25)) scored.push({ u, v, score });
    }
  }
  scored.sort((a, b) => b.score - a.score);
  const usedU = new Set();
  const usedV = new Set();
  const map = [];
  for (const s of scored) {
    if (usedU.has(s.u.uid) || usedV.has(s.v.id)) continue;
    // Ambiguous: another candidate for the same lesson scores the same.
    if (scored.some((o) => o !== s && o.v.id === s.v.id && !usedU.has(o.u.uid) && o.score === s.score)) continue;
    usedU.add(s.u.uid);
    usedV.add(s.v.id);
    map.push({ upload: s.u, video: s.v });
  }
  return map.sort((a, b) => a.video.n - b.video.n);
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
  for (const v of missing) log(`- **Lesson video ${v.n} (${v.title}) has no matching upload**`);
  for (const v of unmapped) log(`- Upload "${v.meta?.name || "(untitled)"}" (\`${short(v.uid)}\`) is not an A1 lesson video: ${v.requireSignedURLs ? "signed URLs required" : "**PUBLIC — left unchanged; review it**"}`);

  const evidence = [];
  const mapping = [];
  const captions = [];
  let failures = missing.length;
  let customer = "";
  const reviewed = arg("reviewed") ? JSON.parse(readFileSync(arg("reviewed"), "utf8")) : [];
  log("");
  log("| # | Lesson video | Upload | Id | State | Duration | Est. | Signed | Origins | Downloads | Bare id | Signed token | Expired token | Captions |");
  log("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|");
  for (const { upload, video } of map) {
    const uid = upload.uid;
    let row;
    try {
      // 1. Protect: signed URLs only, Academy hosts only, no downloads.
      await cf(`/stream/${uid}`, { method: "POST", body: { uid, requireSignedURLs: true, allowedOrigins: ORIGINS } });
      const dl = await cf(`/stream/${uid}/downloads`);
      if (dl && Object.keys(dl).length) await cf(`/stream/${uid}/downloads`, { method: "DELETE" });
      // 2. Re-read what Stream actually holds.
      const v = await cf(`/stream/${uid}`);
      const downloads = Object.entries((await cf(`/stream/${uid}/downloads`)) || {}).map(([k, d]) => `${k}:${d.status}`).join(" ") || "none";
      const hls = v.playback?.hls || "";
      customer ||= /^https:\/\/customer-([a-z0-9]+)\.cloudflarestream\.com\//.exec(hls)?.[1] || "";
      const base = hls.replace(/\/[0-9a-f]{32}\/manifest\/video\.m3u8$/, "");
      // 3. Probe from outside, as a stranger would.
      const bare = await anonymous(hls);
      const bareMp4 = await anonymous(`${base}/${uid}/downloads/default.mp4`);
      const fresh = await cf(`/stream/${uid}/token`, { method: "POST", body: { exp: Math.floor(Date.now() / 1000) + 300, downloadable: false } });
      const signed = await anonymous(`${base}/${fresh.token}/manifest/video.m3u8`);
      // A token that has expired (valid for 2 s, used after 5 s) must be refused.
      const brief = await cf(`/stream/${uid}/token`, { method: "POST", body: { exp: Math.floor(Date.now() / 1000) + 2, downloadable: false } });
      await sleep(5000);
      const expired = await anonymous(`${base}/${brief.token}/manifest/video.m3u8`);
      const ok = v.requireSignedURLs === true && downloads === "none" && bare >= 400 && bareMp4 >= 400 && expired >= 400 && signed === 200 && ORIGINS.every((o) => (v.allowedOrigins || []).includes(o));
      if (!ok) failures++;
      const duration = Math.round(v.duration || 0);
      // 4. Captions: Stream's machine captions become drafts for review;
      // reviewed captions from the Academy replace them in the player.
      let caps = (await cf(`/stream/${uid}/captions`)) || [];
      const mine = reviewed.find((r) => r.video_id === video.id && r.locale.split("-")[0] === "en");
      if (mine) {
        const current = caps.find((c) => c.language === "en");
        const live = current && !current.generated ? (await cf(`/stream/${uid}/captions/en/vtt`, { raw: true })).text : "";
        if (live.trim() !== mine.vtt.trim()) {
          const fd = new FormData();
          fd.append("file", new Blob([mine.vtt], { type: "text/vtt" }), "en.vtt");
          await cf(`/stream/${uid}/captions/en`, { method: "PUT", body: fd });
        }
      } else if (!caps.some((c) => c.language === "en") && process.env.STREAM_GENERATE_CAPTIONS === "1" && v.readyToStream) {
        await cf(`/stream/${uid}/captions/en/generate`, { method: "POST" });
      }
      caps = (await cf(`/stream/${uid}/captions`)) || [];
      const machine = caps.find((c) => c.language === "en" && c.generated && (c.status || "ready") === "ready");
      if (machine && !mine) {
        const vtt = (await cf(`/stream/${uid}/captions/en/vtt`, { raw: true })).text;
        if (vtt.startsWith("WEBVTT"))
          captions.push(
            `INSERT INTO video_captions (id, video_id, locale, label, vtt, status, created_at) VALUES (${sql(`cap_${video.id.slice(4)}_en`)}, ${sql(video.id)}, 'en', 'English', ${sql(vtt)}, 'machine', ${sql(new Date().toISOString())}) ON CONFLICT(video_id, locale) DO UPDATE SET vtt = excluded.vtt WHERE video_captions.status = 'machine' AND video_captions.vtt <> excluded.vtt;`,
          );
      }
      const capDesc = caps.map((c) => `${c.language}${c.generated ? " (machine)" : ""}:${c.status || "ready"}`).join(" ") || "none";
      evidence.push(
        `INSERT OR REPLACE INTO stream_protection (uid, title, duration_seconds, signed_required, allowed_origins, downloads, anonymous_status, checked_at) VALUES (${[uid, upload.name, duration, v.requireSignedURLs ? 1 : 0, (v.allowedOrigins || []).join(" "), downloads, ok ? Math.min(bare, bareMp4, expired) : 200, new Date().toISOString()].map(sql).join(", ")});`,
      );
      if (v.readyToStream && duration > 0)
        mapping.push(
          `UPDATE video_assets SET provider = 'stream', provider_ref = ${sql(uid)}, duration_seconds = ${duration}, updated_at = ${sql(new Date().toISOString())} WHERE id = ${sql(video.id)} AND COALESCE(provider_ref, '') IN ('', ${sql(uid)}) AND (provider <> 'stream' OR COALESCE(provider_ref, '') <> ${sql(uid)} OR COALESCE(duration_seconds, 0) <> ${duration});`,
        );
      const est = video.minutes * 60;
      const drift = duration && Math.abs(duration - est) / est > 0.5 ? " ⚠" : "";
      row = `| ${video.n} | ${video.title} | ${upload.name} | \`${short(uid)}\` | ${v.status?.state || "?"} | ${Math.floor(duration / 60)}:${String(duration % 60).padStart(2, "0")} | ${video.minutes} min${drift} | ${v.requireSignedURLs ? "yes" : "**NO**"} | ${(v.allowedOrigins || []).join(" ") || "**any**"} | ${downloads} | ${bare}${bareMp4 >= 400 ? "" : ` mp4 ${bareMp4}`} | ${signed} | ${expired} | ${capDesc} |${ok ? "" : " **NOT PROTECTED**"}`;
    } catch (e) {
      failures++;
      row = `| ${video.n} | ${video.title} | ${upload.name} | \`${short(uid)}\` | **error: ${String(e.message).slice(0, 120)}** |`;
    }
    log(row);
  }
  writeFileSync(join(out, "evidence.sql"), evidence.join("\n") + "\n");
  writeFileSync(join(out, "mapping.sql"), mapping.join("\n") + "\n");
  writeFileSync(join(out, "captions.sql"), captions.join("\n") + "\n");
  writeFileSync(join(out, "customer-code"), customer);
  log("");
  log(`- Bare id, expired token: HTTP status for a request without a valid token (must be 401/403). Signed token: a fresh 5-minute token (must be 200). Est.: the lesson's displayed time (⚠ when the video differs by more than half).`);
  log(`- Machine captions imported as drafts for review: ${captions.length}`);
  log(failures ? `- **${failures} lesson video(s) not verifiably protected.**` : `- All ${map.length} mapped lesson videos verified private.`);
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, lines.join("\n") + "\n");
  process.exit(failures ? 1 : 0);
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
