// Reflows an unreviewed machine caption draft for readability, for the
// caption reviewer. It changes layout and timing only: the words, in order,
// are exactly those of the draft, and every cue still covers the speech of
// the draft's cues. It never marks a caption reviewed.
//
//   - lines wrapped to at most two of 42 characters, broken at punctuation
//     where possible;
//   - a cue shorter than 1 s, or read faster than 20 characters per second,
//     is merged with a neighbour when they are close together and the
//     result fits two lines, lasts at most 7 s and reads no faster;
//   - a cue too long for two lines is split at a sentence or clause break
//     near its middle; its time is divided in proportion to the text (the
//     only estimated timing, counted in the report for the reviewer);
//   - a cue's end is extended into the silence before the next cue, so it
//     stays on screen long enough to read; a start is never moved earlier.
//
//   node scripts/caption-reflow.mjs --query                 the drafts to read (SQL)
//   node scripts/caption-reflow.mjs --in drafts.json --out reflow.sql
// drafts.json: [{ id, video_id, vtt, duration }]. Prints a before/after QA
// table (counts only, never caption text, since logs may be public) and
// writes guarded UPDATEs. Any violated invariant fails the run and nothing is
// written.
import { readFileSync, writeFileSync } from "node:fs";
import { LIMITS, captionQa } from "./caption-qa.mjs";

const MERGE_GAP = 500; // ms: cues further apart are separate utterances
const len = (s) => [...s].length;

const toMs = (t) => {
  const p = t.trim().split(":").map(Number);
  const s = p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
  return Math.round(s * 1000);
};
const fmt = (ms) => {
  const h = Math.floor(ms / 3600000);
  const m = Math.floor(ms / 60000) % 60;
  const s = Math.floor(ms / 1000) % 60;
  const pad = (n, w = 2) => String(n).padStart(w, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)}.${pad(ms % 1000, 3)}`;
};

/** Header block and cues ({ start, end, settings, text } with times in ms) of a WebVTT file. */
export function parse(vtt) {
  const blocks = String(vtt).replace(/\r\n?/g, "\n").split(/\n{2,}/);
  const header = blocks.shift().trim();
  if (!header.startsWith("WEBVTT")) throw new Error("not a WebVTT file");
  const cues = [];
  for (const b of blocks) {
    const lines = b.split("\n").filter((l) => l.trim());
    const i = lines.findIndex((l) => l.includes("-->"));
    if (i < 0) continue; // NOTE, STYLE and REGION blocks carry no spoken words
    const [a, rest] = lines[i].split("-->");
    const [z, ...settings] = rest.trim().split(/\s+/);
    const text = lines
      .slice(i + 1)
      .map((l) => l.replace(/<[^>]+>/g, "").trim())
      .filter(Boolean)
      .join(" ");
    cues.push({ start: toMs(a), end: toMs(z), settings: settings.join(" "), text });
  }
  return { header, cues };
}

const words = (cues) => cues.flatMap((c) => c.text.split(/\s+/).filter(Boolean));
const cps = (c) => len(c.text) / Math.max((c.end - c.start) / 1000, 0.001);

/** The text on at most two lines of at most 42 characters, or null if it does not fit. */
export function wrap(text) {
  if (len(text) <= LIMITS.lineChars) return [text];
  let best = null;
  for (let i = text.indexOf(" "); i > 0; i = text.indexOf(" ", i + 1)) {
    const a = text.slice(0, i);
    const b = text.slice(i + 1);
    if (len(a) > LIMITS.lineChars || len(b) > LIMITS.lineChars) continue;
    // Balanced lines, broken after punctuation and not after a short function word.
    const score = Math.abs(len(a) - len(b)) - (/[.?!]$/.test(a) ? 20 : /[,;:]$/.test(a) ? 10 : 0) + (/\b(a|an|the|of|to|and|or|in|on|for|with)$/i.test(a) ? 8 : 0);
    if (!best || score < best.score) best = { score, lines: [a, b] };
  }
  return best && best.lines;
}

/** Split a cue whose text does not fit two lines, recursively, dividing its time by the text. */
function split(cue) {
  const toks = cue.text.split(" ");
  if (wrap(cue.text) || toks.length < 2) return [cue];
  let best = null;
  for (let k = 1; k < toks.length; k++) {
    const a = toks.slice(0, k).join(" ");
    const share = len(a) / len(cue.text);
    const score = Math.abs(share - 0.5) * 100 - (/[.?!]$/.test(a) ? 30 : /[,;:]$/.test(a) ? 15 : 0);
    if (!best || score < best.score) best = { score, k, share };
  }
  const at = cue.start + Math.round((cue.end - cue.start) * best.share);
  const a = { ...cue, end: at, text: toks.slice(0, best.k).join(" "), estimated: true };
  const b = { ...cue, start: at, text: toks.slice(best.k).join(" "), estimated: true };
  return [...split(a), ...split(b)];
}

const join = (a, b) => ({ ...a, end: b.end, text: `${a.text} ${b.text}`, src: [...a.src, ...b.src], estimated: a.estimated || b.estimated, merged: true });
const mergeable = (a, b) => {
  if (b.start - a.end > MERGE_GAP) return false;
  const m = join(a, b);
  // Reading speed may rise by at most 5% (a sub-second flash is harder to read than that).
  return m.end - m.start <= LIMITS.maxCue * 1000 && Boolean(wrap(m.text)) && cps(m) <= Math.max(cps(a), cps(b), LIMITS.cps) * 1.05;
};

/** Merge cues shown too briefly or read too fast with a close neighbour, while the result stays readable. */
function mergePass(cues) {
  const out = cues.slice();
  for (let changed = true; changed; ) {
    changed = false;
    for (let i = 0; i < out.length; i++) {
      const c = out[i];
      if (c.end - c.start >= LIMITS.minCue * 1000 && cps(c) <= LIMITS.cps) continue;
      const prev = i > 0 && mergeable(out[i - 1], c) ? c.start - out[i - 1].end : Infinity;
      const next = i < out.length - 1 && mergeable(c, out[i + 1]) ? out[i + 1].start - c.end : Infinity;
      if (prev === Infinity && next === Infinity) continue;
      if (prev <= next) out.splice(i - 1, 2, join(out[i - 1], c));
      else out.splice(i, 2, join(c, out[i + 1]));
      changed = true;
      break;
    }
  }
  return out;
}

/**
 * Reflow a caption. `durationMs` is the video's length (0 when unknown: no
 * cue then ends later than the draft's last cue). Returns the new WebVTT and
 * what changed; throws if any invariant would be violated.
 */
export function reflow(vtt, durationMs = 0) {
  const { header, cues: orig } = parse(vtt);
  if (!orig.length) throw new Error("no cues");
  const limit = Math.max(durationMs || 0, ...orig.map((c) => c.end));
  let cues = orig.map((c, i) => ({ ...c, src: [i] }));
  cues = cues.flatMap(split);
  cues = mergePass(cues);
  let extended = 0;
  for (let i = 0; i < cues.length; i++) {
    const c = cues[i];
    const need = Math.max(LIMITS.minCue * 1000, Math.ceil((len(c.text) / LIMITS.cps) * 1000));
    const room = Math.min(i < cues.length - 1 ? cues[i + 1].start : limit, limit, c.start + LIMITS.maxCue * 1000);
    const end = Math.min(c.start + need, room);
    if (end > c.end) {
      c.end = end;
      extended++;
    }
  }
  check(orig, cues, limit);
  const body = cues.map((c) => `${fmt(c.start)} --> ${fmt(c.end)}${c.settings ? ` ${c.settings}` : ""}\n${wrap(c.text).join("\n")}`);
  return {
    vtt: `${header}\n\n${body.join("\n\n")}\n`,
    merged: cues.filter((c) => c.merged).length,
    estimated: cues.filter((c) => c.estimated).length,
    extended,
  };
}

/** The invariants: same words in the same order, no overlap, within the video, every draft cue's speech still covered. */
function check(orig, cues, limit) {
  const a = words(orig);
  const b = words(cues);
  if (a.length !== b.length || a.some((w, i) => w !== b[i])) throw new Error("words changed");
  // Which draft cue each word came from, and which new cue it is now in.
  const from = orig.flatMap((c, i) => c.text.split(/\s+/).filter(Boolean).map(() => i));
  const into = cues.flatMap((c, i) => c.text.split(/\s+/).filter(Boolean).map(() => i));
  cues.forEach((c, i) => {
    if (!(c.start >= 0 && c.end > c.start && c.end <= limit)) throw new Error(`cue ${i + 1} timing out of range`);
    if (i && c.start < cues[i - 1].end) throw new Error(`cue ${i + 1} overlaps the previous cue`);
    if (!wrap(c.text)) throw new Error(`cue ${i + 1} does not fit two lines`);
    if (c.start < orig[from[into.indexOf(i)]].start) throw new Error(`cue ${i + 1} starts before its speech`);
  });
  orig.forEach((o, i) => {
    const holders = [...new Set(into.filter((_, w) => from[w] === i))].map((j) => cues[j]);
    if (!holders.length) return; // a cue without words
    if (Math.min(...holders.map((c) => c.start)) > o.start || Math.max(...holders.map((c) => c.end)) < o.end) throw new Error(`speech of draft cue ${i + 1} is no longer covered`);
  });
}

/** The drafts the deploy reflows: unreviewed, never reflowed before (so a reviewer's edits are never overwritten). */
export const DRAFTS_SQL =
  "SELECT vc.id, vc.video_id, vc.vtt, va.duration_seconds AS duration FROM video_captions vc JOIN video_assets va ON va.id = vc.video_id WHERE vc.status = 'machine' AND vc.source_vtt IS NULL ORDER BY vc.video_id";

const sqlStr = (s) => `'${String(s).replace(/'/g, "''")}'`;
const RELEASED = (v) =>
  `EXISTS (SELECT 1 FROM lessons l JOIN courses c ON c.id = l.course_id WHERE l.video_id = ${v} AND c.published_at IS NOT NULL)`;

/** Guarded write: only an unreviewed draft never reflowed before, unchanged since it was read, of an unreleased video. */
export function updateSql(row, vtt, now) {
  return `UPDATE video_captions SET source_vtt = vtt, vtt = ${sqlStr(vtt)}, reflowed_at = ${sqlStr(now)} WHERE id = ${sqlStr(row.id)} AND status = 'machine' AND source_vtt IS NULL AND vtt = ${sqlStr(row.vtt)} AND NOT ${RELEASED("video_captions.video_id")};`;
}

const cell = (q) => `${q.cues} | ${q.counts.long} | ${q.counts.fast} | ${q.counts.short} | ${q.counts.lengthy} | ${q.counts.overlaps}`;

/** Reflow every draft; returns the SQL and a Markdown report, or throws naming the drafts that failed. */
export function reflowAll(rows, now = new Date().toISOString()) {
  const sql = [];
  const failed = [];
  const out = [
    "| Video | Before: cues · long lines · fast · short · over 7 s · overlaps | After: cues · long lines · fast · short · over 7 s · overlaps | Merged | Estimated timing | Extended |",
    "|---|---|---|---|---|---|",
  ];
  for (const row of rows) {
    const sec = Number(row.duration) || 0;
    try {
      const r = reflow(row.vtt, sec * 1000);
      const before = captionQa(row.vtt, sec);
      const after = captionQa(r.vtt, sec);
      out.push(`| ${row.video_id} | ${cell(before)} | ${cell(after)} | ${r.merged} | ${r.estimated} | ${r.extended} |`);
      if (r.vtt !== row.vtt) sql.push(updateSql(row, r.vtt, now));
    } catch (e) {
      failed.push(`${row.video_id}: ${e.message}`);
    }
  }
  if (failed.length) throw new Error(`reflow refused, nothing written:\n- ${failed.join("\n- ")}`);
  return { sql, report: out.join("\n") };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const arg = (n) => process.argv[process.argv.indexOf(`--${n}`) + 1];
  if (process.argv.includes("--query")) {
    console.log(DRAFTS_SQL);
    process.exit(0);
  }
  const rows = JSON.parse(readFileSync(arg("in"), "utf8"));
  try {
    const { sql, report } = reflowAll(rows);
    writeFileSync(arg("out"), sql.join("\n") + (sql.length ? "\n" : ""));
    console.log(`Machine caption drafts awaiting a first reflow: ${rows.length}; reflowed: ${sql.length}. Every result stays an unreviewed draft, hidden from learners.`);
    if (rows.length) console.log(`\n${report}\n\nLong lines: a line over ${LIMITS.lineChars} characters. Fast: over ${LIMITS.cps} characters per second. Short: under ${LIMITS.minCue} s. Estimated timing: cues split from a draft cue too long for two lines, timed in proportion to their text; the reviewer checks their sync. Splitting a fast cue counts each part as fast: the speaking rate itself is unchanged, and the reviewer may condense such text.`);
  } catch (e) {
    console.error(`::error::${e.message}`);
    process.exit(1);
  }
}
