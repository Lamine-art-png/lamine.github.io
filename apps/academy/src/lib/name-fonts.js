// Fonts used to print learner names on certificate PDFs, by script. The font
// files live in public/static/fonts/pdf/ (licenses alongside) and are read
// through the static-assets binding. A script with no entry is unsupported:
// the PDF then asks the learner for a Latin-script credential name instead.
export const NAME_FONTS = {
  "serif-bold": { file: "DejaVuSerif-Bold.ttf", scripts: ["latn", "grek", "cyrl", "armn", "geor"] },
  "sans-bold": { file: "DejaVuSans-Bold.ttf", scripts: ["arab", "hebr", "latn", "grek", "cyrl", "armn", "geor"] },
  "indic-bold": { file: "FreeSerifBold.ttf", scripts: ["deva", "guru", "taml", "knda", "mlym", "thai", "arab", "hebr"] },
  indic: { file: "FreeSerif.ttf", scripts: ["deva", "beng", "guru", "gujr", "taml", "knda", "mlym", "thai", "ethi", "arab", "hebr"] },
  cjk: { file: "WenQuanYiZenHei-Names.ttf", scripts: ["hani", "kana", "hang", "bopo", "latn"] },
};

/** Candidate font keys for a script, in order of preference. */
export const fontKeysFor = (script) => Object.keys(NAME_FONTS).filter((k) => NAME_FONTS[k].scripts.includes(script));

const visible = (cp) => cp > 0x20 && cp !== 0xa0 && cp !== 0x200c && cp !== 0x200d && !(cp >= 0xfe00 && cp <= 0xfe0f);

/** First candidate font (key) that has a glyph for every visible character of the run. */
export function pickNameFont(script, cps, getFont) {
  for (const key of fontKeysFor(script)) {
    const font = getFont(key);
    if (font && cps.every((cp) => !visible(cp) || font.glyphForCodePoint(cp))) return key;
  }
  return null;
}

/**
 * Fonts for a whole name: one font for every script when a single font covers
 * them all (Latin and Arabic from the same family, for example), otherwise the
 * best font per script. `byScript` maps script → code points (in text order;
 * the first entry is the name's primary script). Returns Map(script → key|null).
 */
export function chooseNameFonts(byScript, getFont) {
  const scripts = [...byScript.keys()];
  const all = scripts.flatMap((sc) => byScript.get(sc));
  const primary = scripts[0];
  const shared = fontKeysFor(primary).find((key) => scripts.every((sc) => NAME_FONTS[key].scripts.includes(sc)) && pickNameFont(primary, all, (k) => (k === key ? getFont(k) : null)));
  return new Map(scripts.map((sc) => [sc, shared || pickNameFont(sc, byScript.get(sc), getFont)]));
}
