// Compact Unicode data for shaping certificate names: scripts, bidi classes,
// Arabic joining types and Indic character categories. Covers the scripts the
// Academy's languages use; anything else is reported as unsupported.

/** [start, end, script] — OpenType script tags; "zyyy" common, "zinh" inherited. */
const SCRIPT_RANGES = [
  [0x0000, 0x0040, "zyyy"], [0x0041, 0x005a, "latn"], [0x005b, 0x0060, "zyyy"], [0x0061, 0x007a, "latn"], [0x007b, 0x00a9, "zyyy"],
  [0x00aa, 0x00aa, "latn"], [0x00ab, 0x00b9, "zyyy"], [0x00ba, 0x00ba, "latn"], [0x00bb, 0x00bf, "zyyy"], [0x00c0, 0x00d6, "latn"],
  [0x00d7, 0x00d7, "zyyy"], [0x00d8, 0x00f6, "latn"], [0x00f7, 0x00f7, "zyyy"], [0x00f8, 0x02af, "latn"], [0x02b0, 0x02ff, "zyyy"],
  [0x0300, 0x036f, "zinh"], [0x0370, 0x03ff, "grek"], [0x0400, 0x052f, "cyrl"], [0x0531, 0x058f, "armn"], [0x0591, 0x05ff, "hebr"],
  [0x0600, 0x060b, "arab"], [0x060c, 0x060c, "zyyy"], [0x060d, 0x061a, "arab"], [0x061b, 0x061b, "zyyy"], [0x061c, 0x061e, "arab"],
  [0x061f, 0x061f, "zyyy"], [0x0620, 0x063f, "arab"], [0x0640, 0x0640, "zyyy"], [0x0641, 0x064a, "arab"], [0x064b, 0x0655, "zinh"],
  [0x0656, 0x066f, "arab"], [0x0670, 0x0670, "zinh"], [0x0671, 0x06ff, "arab"], [0x0750, 0x077f, "arab"], [0x08a0, 0x08ff, "arab"],
  [0x0900, 0x0950, "deva"], [0x0951, 0x0954, "zinh"], [0x0955, 0x0963, "deva"], [0x0964, 0x0965, "zyyy"], [0x0966, 0x097f, "deva"],
  [0x0980, 0x09ff, "beng"], [0x0a00, 0x0a7f, "guru"], [0x0a80, 0x0aff, "gujr"], [0x0b00, 0x0b7f, "orya"], [0x0b80, 0x0bff, "taml"],
  [0x0c00, 0x0c7f, "telu"], [0x0c80, 0x0cff, "knda"], [0x0d00, 0x0d7f, "mlym"], [0x0d80, 0x0dff, "sinh"], [0x0e00, 0x0e7f, "thai"],
  [0x0e80, 0x0eff, "lao "], [0x0f00, 0x0fff, "tibt"], [0x1000, 0x109f, "mymr"], [0x10a0, 0x10ff, "geor"], [0x1100, 0x11ff, "hang"],
  [0x1200, 0x139f, "ethi"], [0x1780, 0x17ff, "khmr"], [0x1ab0, 0x1aff, "zinh"], [0x1c90, 0x1cbf, "geor"], [0x1dc0, 0x1dff, "zinh"],
  [0x1e00, 0x1eff, "latn"], [0x1f00, 0x1fff, "grek"], [0x2000, 0x200b, "zyyy"], [0x200c, 0x200d, "zinh"], [0x200e, 0x20cf, "zyyy"],
  [0x20d0, 0x20ff, "zinh"], [0x2100, 0x2e7f, "zyyy"], [0x2e80, 0x2fdf, "hani"], [0x3000, 0x303f, "zyyy"], [0x3040, 0x309f, "kana"],
  [0x30a0, 0x30ff, "kana"], [0x3100, 0x312f, "bopo"], [0x3130, 0x318f, "hang"], [0x3190, 0x31ff, "hani"], [0x3400, 0x4dbf, "hani"],
  [0x4e00, 0x9fff, "hani"], [0xa960, 0xa97f, "hang"], [0xa980, 0xa9df, "java"], [0xac00, 0xd7ff, "hang"], [0xf900, 0xfaff, "hani"],
  [0xfb1d, 0xfb4f, "hebr"], [0xfb50, 0xfdff, "arab"], [0xfe00, 0xfe0f, "zinh"], [0xfe20, 0xfe2f, "zinh"], [0xfe30, 0xfe4f, "zyyy"],
  [0xfe70, 0xfeff, "arab"], [0xff00, 0xff20, "zyyy"], [0xff21, 0xff3a, "latn"], [0xff41, 0xff5a, "latn"], [0xff61, 0xff9f, "kana"],
  [0x20000, 0x3134f, "hani"],
];

export function scriptOf(cp) {
  let lo = 0;
  let hi = SCRIPT_RANGES.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const [a, b, s] = SCRIPT_RANGES[mid];
    if (cp < a) hi = mid - 1;
    else if (cp > b) lo = mid + 1;
    else return s;
  }
  return "zyyy";
}

export const RTL_SCRIPTS = new Set(["arab", "hebr"]);

/** Simplified bidi class: L, R, AL, EN, AN, NSM (marks), WS, ON. */
export function bidiClass(cp) {
  if (cp >= 0x30 && cp <= 0x39) return "EN";
  if (cp >= 0x660 && cp <= 0x669) return "AN";
  if (cp >= 0x6f0 && cp <= 0x6f9) return "EN";
  if (cp === 0x20 || cp === 0xa0 || (cp >= 0x2000 && cp <= 0x200a)) return "WS";
  if (cp === 0x200c || cp === 0x200d) return "NSM";
  if (isMark(cp)) return "NSM";
  const s = scriptOf(cp);
  if (s === "hebr") return "R";
  if (s === "arab") return "AL";
  if (s === "zyyy" || s === "zinh") return "ON";
  return "L";
}

/** Combining (non-spacing or enclosing) marks, approximated by block. */
export function isMark(cp) {
  return (
    (cp >= 0x300 && cp <= 0x36f) || (cp >= 0x483 && cp <= 0x489) || (cp >= 0x591 && cp <= 0x5bd) || cp === 0x5bf || cp === 0x5c1 || cp === 0x5c2 ||
    cp === 0x5c4 || cp === 0x5c5 || cp === 0x5c7 || (cp >= 0x610 && cp <= 0x61a) || (cp >= 0x64b && cp <= 0x65f) || cp === 0x670 ||
    (cp >= 0x6d6 && cp <= 0x6dc) || (cp >= 0x6df && cp <= 0x6e4) || cp === 0x6e7 || cp === 0x6e8 || (cp >= 0x6ea && cp <= 0x6ed) ||
    (cp >= 0x1ab0 && cp <= 0x1aff) || (cp >= 0x1dc0 && cp <= 0x1dff) || (cp >= 0x20d0 && cp <= 0x20ff) || (cp >= 0xfe20 && cp <= 0xfe2f) ||
    cp === 0xe31 || (cp >= 0xe34 && cp <= 0xe3a) || (cp >= 0xe47 && cp <= 0xe4e)
  );
}

const MIRROR = { 0x28: 0x29, 0x29: 0x28, 0x3c: 0x3e, 0x3e: 0x3c, 0x5b: 0x5d, 0x5d: 0x5b, 0x7b: 0x7d, 0x7d: 0x7b, 0xab: 0xbb, 0xbb: 0xab };
export const mirrored = (cp) => MIRROR[cp] ?? cp;

// ───────────── Arabic joining ─────────────
const ARABIC_R = new Set([
  0x622, 0x623, 0x624, 0x625, 0x627, 0x629, 0x62f, 0x630, 0x631, 0x632, 0x648, 0x671, 0x672, 0x673, 0x675, 0x676, 0x677,
  0x688, 0x689, 0x68a, 0x68b, 0x68c, 0x68d, 0x68e, 0x68f, 0x690, 0x691, 0x692, 0x693, 0x694, 0x695, 0x696, 0x697, 0x698, 0x699,
  0x6c0, 0x6c3, 0x6c4, 0x6c5, 0x6c6, 0x6c7, 0x6c8, 0x6c9, 0x6ca, 0x6cb, 0x6cd, 0x6cf, 0x6d2, 0x6d3, 0x6d5, 0x6ee, 0x6ef,
]);
const ARABIC_U = new Set([0x621, 0x674]);

/** Arabic joining type: R, D, U, T (transparent), C (join-causing). */
export function joiningType(cp) {
  if (cp === 0x640 || cp === 0x200d) return "C";
  if (isMark(cp) || (cp >= 0x610 && cp <= 0x61a)) return "T";
  if (ARABIC_R.has(cp)) return "R";
  if (ARABIC_U.has(cp)) return "U";
  if ((cp >= 0x620 && cp <= 0x64a) || (cp >= 0x66e && cp <= 0x6d3) || (cp >= 0x6fa && cp <= 0x6ff) || (cp >= 0x750 && cp <= 0x77f)) return "D";
  return "U";
}

// ───────────── Indic ─────────────
// Indic blocks share the ISCII-derived layout; categories are given by offset.
export const INDIC_SCRIPTS = {
  deva: { base: 0x0900, virama: 0x094d, rephPos: "BEFORE_POST", blwfPostOnly: false },
  beng: { base: 0x0980, virama: 0x09cd, rephPos: "AFTER_SUB", blwfPostOnly: false },
  guru: { base: 0x0a00, virama: 0x0a4d, rephPos: "BEFORE_SUB", blwfPostOnly: false },
  gujr: { base: 0x0a80, virama: 0x0acd, rephPos: "BEFORE_POST", blwfPostOnly: false },
  orya: { base: 0x0b00, virama: 0x0b4d, rephPos: "AFTER_MAIN", blwfPostOnly: false },
  taml: { base: 0x0b80, virama: 0x0bcd, rephPos: "AFTER_POST", blwfPostOnly: false },
  telu: { base: 0x0c00, virama: 0x0c4d, rephPos: "AFTER_POST", blwfPostOnly: true },
  knda: { base: 0x0c80, virama: 0x0ccd, rephPos: "AFTER_POST", blwfPostOnly: true },
  mlym: { base: 0x0d00, virama: 0x0d4d, rephPos: "AFTER_MAIN", blwfPostOnly: false },
};

// Matra side by block offset (0x3e–0x4c, 0x55–0x57, 0x62–0x63) and script overrides.
const MATRA_SIDE_DEFAULT = {
  0x3e: "post", 0x3f: "pre", 0x40: "post", 0x41: "below", 0x42: "below", 0x43: "below", 0x44: "below", 0x45: "above", 0x46: "above",
  0x47: "above", 0x48: "above", 0x49: "post", 0x4a: "post", 0x4b: "post", 0x4c: "post", 0x4e: "pre", 0x4f: "post", 0x55: "above", 0x56: "below",
  0x57: "post", 0x62: "below", 0x63: "below",
};
const MATRA_SIDE_SCRIPT = {
  beng: { 0x47: "pre", 0x48: "pre", 0x4b: "split", 0x4c: "split", 0x57: "post" },
  guru: { 0x47: "above", 0x48: "above", 0x4b: "above", 0x4c: "above" },
  gujr: { 0x45: "above", 0x47: "above", 0x48: "above", 0x49: "post", 0x4b: "post", 0x4c: "post" },
  orya: { 0x3f: "above", 0x40: "post", 0x47: "pre", 0x48: "split", 0x4b: "split", 0x4c: "split", 0x56: "above", 0x57: "post" },
  taml: { 0x3f: "post", 0x40: "above", 0x41: "post", 0x42: "post", 0x46: "pre", 0x47: "pre", 0x48: "pre", 0x4a: "split", 0x4b: "split", 0x4c: "split", 0x57: "post" },
  telu: { 0x3e: "above", 0x3f: "above", 0x40: "above", 0x41: "post", 0x42: "post", 0x43: "post", 0x44: "post", 0x46: "above", 0x47: "above", 0x48: "split", 0x4a: "above", 0x4b: "above", 0x4c: "above", 0x55: "above", 0x56: "below" },
  knda: { 0x3e: "post", 0x3f: "above", 0x40: "split", 0x41: "post", 0x42: "post", 0x43: "post", 0x44: "post", 0x46: "above", 0x47: "split", 0x48: "split", 0x4a: "split", 0x4b: "split", 0x4c: "above", 0x55: "post", 0x56: "post" },
  mlym: { 0x3e: "post", 0x3f: "post", 0x40: "post", 0x41: "below", 0x42: "below", 0x43: "below", 0x44: "below", 0x46: "pre", 0x47: "pre", 0x48: "pre", 0x4a: "split", 0x4b: "split", 0x4c: "split", 0x57: "post" },
};

/** Canonical decompositions of two-part (split) vowel signs. */
export const SPLIT_MATRAS = {
  0x09cb: [0x09c7, 0x09be], 0x09cc: [0x09c7, 0x09d7], 0x0b48: [0x0b47, 0x0b56], 0x0b4b: [0x0b47, 0x0b3e], 0x0b4c: [0x0b47, 0x0b57],
  0x0bca: [0x0bc6, 0x0bbe], 0x0bcb: [0x0bc7, 0x0bbe], 0x0bcc: [0x0bc6, 0x0bd7], 0x0c48: [0x0c46, 0x0c56], 0x0cc0: [0x0cbf, 0x0cd5],
  0x0cc7: [0x0cc6, 0x0cd5], 0x0cc8: [0x0cc6, 0x0cd6], 0x0cca: [0x0cc6, 0x0cc2], 0x0ccb: [0x0cc6, 0x0cc2, 0x0cd5], 0x0d4a: [0x0d46, 0x0d3e],
  0x0d4b: [0x0d47, 0x0d3e], 0x0d4c: [0x0d46, 0x0d57],
};

// Positions, in reordering order (as in the OpenType Indic shaping model).
export const POS = { START: 0, RA_TO_BECOME_REPH: 1, PRE_M: 2, PRE_C: 3, BASE_C: 4, AFTER_MAIN: 5, ABOVE_C: 6, BEFORE_SUB: 7, BELOW_C: 8, AFTER_SUB: 9, BEFORE_POST: 10, POST_C: 11, AFTER_POST: 12, SMVD: 13, END: 14 };

function matraPosition(script, side, cp) {
  const o = cp - INDIC_SCRIPTS[script].base;
  if (side === "pre") return POS.PRE_M;
  if (side === "post") {
    if (script === "deva") return POS.AFTER_SUB;
    if (script === "telu") return o <= 0x42 ? POS.BEFORE_SUB : POS.AFTER_SUB;
    if (script === "knda") return o < 0x43 || o > 0x56 ? POS.BEFORE_SUB : POS.AFTER_SUB;
    return POS.AFTER_POST;
  }
  if (side === "above") return { deva: POS.AFTER_SUB, guru: POS.AFTER_POST, gujr: POS.AFTER_SUB, orya: POS.AFTER_MAIN, taml: POS.AFTER_SUB, telu: POS.BEFORE_SUB, knda: POS.BEFORE_SUB }[script] ?? POS.AFTER_SUB;
  if (side === "below") return { guru: POS.AFTER_POST, gujr: POS.AFTER_POST, taml: POS.AFTER_POST, telu: POS.BEFORE_SUB, knda: POS.BEFORE_SUB, mlym: POS.AFTER_POST }[script] ?? POS.AFTER_SUB;
  return POS.END;
}

/**
 * Indic category and initial position of a character in `script`:
 * C consonant, Ra, V vowel, M matra, H virama, N nukta, SM modifier,
 * ZWJ, ZWNJ, Repha (pre-encoded reph), PLACEHOLDER, X other.
 */
export function indicInfo(script, cp) {
  if (cp === 0x200d) return { cat: "ZWJ", pos: POS.END };
  if (cp === 0x200c) return { cat: "ZWNJ", pos: POS.END };
  if (cp === 0x25cc || cp === 0xa0) return { cat: "PLACEHOLDER", pos: POS.BASE_C };
  const cfg = INDIC_SCRIPTS[script];
  if (!cfg || cp < cfg.base || cp > cfg.base + 0x7f) return { cat: "X", pos: POS.END };
  const o = cp - cfg.base;
  if (cp === cfg.virama) return { cat: "H", pos: POS.END };
  if (o === 0x3c) return { cat: "N", pos: POS.END };
  if (o >= 0x01 && o <= 0x03) return { cat: "SM", pos: POS.SMVD };
  if (o === 0x00 && script !== "deva") return { cat: "SM", pos: POS.SMVD };
  if (script === "mlym" && o === 0x4e) return { cat: "Repha", pos: POS.RA_TO_BECOME_REPH };
  if (script === "mlym" && o >= 0x7a && o <= 0x7f) return { cat: "C", pos: POS.BASE_C, chillu: true };
  if (script === "beng" && cp === 0x09ce) return { cat: "C", pos: POS.BASE_C };
  if (script === "guru" && (cp === 0x0a70 || cp === 0x0a71)) return { cat: "SM", pos: POS.SMVD };
  if (script === "guru" && (cp === 0x0a72 || cp === 0x0a73)) return { cat: "V", pos: POS.BASE_C };
  if ((o >= 0x04 && o <= 0x14) || o === 0x60 || o === 0x61) return { cat: "V", pos: POS.BASE_C };
  if ((o >= 0x15 && o <= 0x39) || (o >= 0x58 && o <= 0x5f)) {
    const ra = o === 0x30;
    return { cat: ra ? "Ra" : "C", pos: POS.BASE_C };
  }
  const side = (MATRA_SIDE_SCRIPT[script] || {})[o] ?? MATRA_SIDE_DEFAULT[o];
  if (side && ((o >= 0x3e && o <= 0x4c) || (o >= 0x55 && o <= 0x57) || o === 0x62 || o === 0x63 || o === 0x4e || o === 0x4f)) {
    return { cat: "M", pos: matraPosition(script, side === "split" ? "post" : side, cp), side };
  }
  if (o === 0x3d) return { cat: "X", pos: POS.END }; // avagraha
  return { cat: "X", pos: POS.END };
}
