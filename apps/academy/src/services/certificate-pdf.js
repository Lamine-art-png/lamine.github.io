// Certificate PDF rendering with Unicode names: loads the needed fonts from
// the static-assets binding (cached per isolate), shapes the name, and builds
// the PDF.
import { certificatePdf, pdfRepresentable, unsupportedNameScripts } from "../lib/pdf.js";
import { Font } from "../lib/ttf.js";
import { shapeLine, itemize } from "../lib/shape.js";
import { NAME_FONTS, fontKeysFor, chooseNameFonts } from "../lib/name-fonts.js";
import { HttpError } from "../lib/http.js";

const cache = new Map();

async function loadFont(env, origin, key) {
  if (!cache.has(key)) {
    const p = (async () => {
      const res = await env.ASSETS.fetch(new Request(new URL(`/static/fonts/pdf/${NAME_FONTS[key].file}`, origin)));
      if (!res.ok) throw new Error(`font ${key} unavailable (${res.status})`);
      return new Font(await res.arrayBuffer());
    })();
    cache.set(key, p);
    p.catch(() => cache.delete(key));
  }
  return cache.get(key);
}

/** Load every candidate font for the scripts in `name`, then choose and shape. */
export async function shapeName(env, origin, name, size = 40) {
  const scripts = new Set(itemize(name).map((c) => (c.script === "zyyy" ? "latn" : c.script)));
  const keys = new Set([...scripts].flatMap((sc) => fontKeysFor(sc)));
  const fonts = {};
  for (const key of keys) fonts[key] = await loadFont(env, origin, key);
  const line = shapeLine(name, (byScript) => new Map([...chooseNameFonts(byScript, (k) => fonts[k])].map(([sc, k]) => [sc, k ? fonts[k] : null])), size);
  return line;
}

/**
 * Render the certificate. Names that Windows-1252 covers use the standard
 * Times-Bold face as before; others are shaped with embedded fonts. Throws
 * 422 "name_script_unsupported" for writing systems without a font.
 */
export async function renderCertificatePdf(env, origin, cert, opts) {
  if (pdfRepresentable(cert.credential_name)) return certificatePdf(cert, opts);
  if (unsupportedNameScripts(cert.credential_name).length) throw new HttpError(422, "name_script_unsupported");
  const nameLine = await shapeName(env, origin, cert.credential_name);
  if (nameLine.unsupported.length) throw new HttpError(422, "name_script_unsupported");
  return certificatePdf(cert, { ...opts, nameLine });
}
