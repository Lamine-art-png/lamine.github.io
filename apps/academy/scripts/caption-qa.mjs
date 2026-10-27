// Mechanical quality checks on a WebVTT caption, for the caption reviewers.
// It never marks a caption reviewed: a person corrects it against the audio.
// It reports what a machine can measure (layout, timing, reading speed,
// coverage of the video) and course terms that speech recognition commonly
// gets wrong, by count and cue number only (logs may be public).

// Readability limits used by broadcast and accessibility guidance.
export const LIMITS = { lineChars: 42, lines: 2, cps: 20, minCue: 1, maxCue: 7 };

// Course vocabulary a recognizer tends to mishear: [what it should be, pattern for likely errors].
export const TERMS = [
  ["AGRO-AI", /\bagr[oa][\s.]?a\.?\s?i\b|\baggro[\s-]?ai\b|\bagro[\s-]eye\b/gi],
  ["NDVI", /\b(?:and dvi|end vi|nd vi|n d v i|n\. ?d\. ?v\. ?i)\b/gi],
  ["evapotranspiration", /\bevapo[\s-]+transpiration\b|\bevaporate transpiration\b/gi],
  ["ET₀ / ETc", /\be\.? ?t\.? (?:zero|naught|oh)\b|\be t c\b/gi],
  ["Kc (crop coefficient)", /\bkay see\b|\bk c\b/gi],
];

const toSec = (t) => {
  const p = t.trim().split(":").map(Number);
  return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
};

export function parseVtt(vtt) {
  const cues = [];
  const blocks = String(vtt).replace(/\r/g, "").split(/\n{2,}/);
  for (const b of blocks) {
    const lines = b.split("\n").filter(Boolean);
    const i = lines.findIndex((l) => l.includes("-->"));
    if (i < 0) continue;
    const [a, z] = lines[i].split("-->");
    cues.push({ start: toSec(a), end: toSec(z.trim().split(/\s+/)[0]), lines: lines.slice(i + 1).map((l) => l.replace(/<[^>]+>/g, "")) });
  }
  return cues;
}

export function captionQa(vtt, durationSeconds = 0) {
  const issues = [];
  const valid = String(vtt).startsWith("WEBVTT");
  if (!valid) return { valid, cues: 0, issues: ["not a WebVTT file"], terms: {} };
  const cues = parseVtt(vtt);
  let long = 0;
  let tall = 0;
  let fast = 0;
  let short = 0;
  let lengthy = 0;
  let overlaps = 0;
  const terms = {};
  cues.forEach((c, n) => {
    const text = c.lines.join(" ");
    const dur = c.end - c.start;
    if (c.lines.some((l) => [...l].length > LIMITS.lineChars)) long++;
    if (c.lines.length > LIMITS.lines) tall++;
    if (dur > 0 && [...text].length / dur > LIMITS.cps) fast++;
    if (dur < LIMITS.minCue) short++;
    if (dur > LIMITS.maxCue) lengthy++;
    if (n && c.start < cues[n - 1].end - 0.001) overlaps++;
    for (const [term, re] of TERMS) {
      const hits = text.match(re);
      if (hits) (terms[term] ||= []).push(n + 1);
    }
  });
  const last = cues.at(-1)?.end || 0;
  const coverage = durationSeconds ? last / durationSeconds : null;
  if (!cues.length) issues.push("no cues");
  if (long) issues.push(`${long} cue(s) with a line over ${LIMITS.lineChars} characters`);
  if (tall) issues.push(`${tall} cue(s) over ${LIMITS.lines} lines`);
  if (fast) issues.push(`${fast} cue(s) faster than ${LIMITS.cps} characters per second`);
  if (short) issues.push(`${short} cue(s) shorter than ${LIMITS.minCue} s`);
  if (lengthy) issues.push(`${lengthy} cue(s) longer than ${LIMITS.maxCue} s`);
  if (overlaps) issues.push(`${overlaps} overlapping cue(s)`);
  if (coverage != null && (coverage < 0.9 || coverage > 1.02)) issues.push(`captions end at ${Math.round(last)} s of a ${Math.round(durationSeconds)} s video`);
  for (const [term, at] of Object.entries(terms)) issues.push(`possible misrecognition of ${term} at cue ${at.join(", ")}`);
  return { valid, cues: cues.length, words: cues.reduce((s, c) => s + c.lines.join(" ").split(/\s+/).filter(Boolean).length, 0), lastEnd: last, coverage, issues, terms };
}
