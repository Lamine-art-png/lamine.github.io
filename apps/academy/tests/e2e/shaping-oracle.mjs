// Verifies the certificate-name shaper against Chromium's text engine
// (HarfBuzz): each name is drawn twice with the same font file — once by the
// browser (canvas fillText) and once from our shaped glyph outlines — and the
// two rasters must match. Writes a JSON report; exits non-zero on mismatch.
//   node tests/e2e/shaping-oracle.mjs [--only <substring>] [--out report.json] [--images dir]
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { Font } from "../../src/lib/ttf.js";
import { shapeLine } from "../../src/lib/shape.js";
import { NAME_FONTS, chooseNameFonts } from "../../src/lib/name-fonts.js";
import { ORACLE_NAMES } from "./shaping-names.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const args = process.argv.slice(2);
const opt = (k) => (args.includes(k) ? args[args.indexOf(k) + 1] : null);
const only = opt("--only");
const imagesDir = opt("--images");
if (imagesDir) mkdirSync(imagesDir, { recursive: true });

let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch {
  ({ chromium } = await import("/opt/node-tools/node_modules/playwright/index.mjs"));
}

const fontBytes = {};
const fonts = {};
for (const [key, spec] of Object.entries(NAME_FONTS)) {
  fontBytes[key] = readFileSync(join(root, "public/static/fonts/pdf", spec.file));
  fonts[key] = new Font(fontBytes[key]);
}
const SIZE = 64;

const cases = ORACLE_NAMES.filter((c) => !only || c.name.includes(only) || c.label.includes(only));
const prepared = cases.map((c) => {
  const used = new Set();
  const shaped = shapeLine(c.name, (byScript) => {
    const keys = chooseNameFonts(byScript, (k) => fonts[k]);
    for (const k of keys.values()) if (k) used.add(k);
    return new Map([...keys].map(([sc, k]) => [sc, k ? fonts[k] : null]));
  }, SIZE);
  const glyphs = shaped.glyphs.map((g) => {
    const key = Object.keys(fonts).find((k) => fonts[k] === g.font);
    const scale = SIZE / g.font.unitsPerEm;
    return { key, d: g.font.svgPath(g.gid, 0, 0, scale), x: g.x, y: g.y };
  });
  return { ...c, fontKeys: [...used], glyphs, width: shaped.width, unsupported: shaped.unsupported };
});

// Unhinted outlines and fractional advances, so the browser lays out glyphs
// exactly as the font specifies (Linux CI otherwise rounds advances to pixels).
const browser = await chromium.launch({ args: ["--font-render-hinting=none"] });
const page = await browser.newPage({ viewport: { width: 1400, height: 400 } });
await page.route("https://oracle.test/**", (route) => {
  const u = new URL(route.request().url());
  if (u.pathname.startsWith("/fonts/")) return route.fulfill({ body: fontBytes[u.pathname.slice(7)], headers: { "content-type": "font/ttf" } });
  return route.fulfill({ body: "<!doctype html><meta charset=utf-8><body></body>", headers: { "content-type": "text/html" } });
});
await page.goto("https://oracle.test/");
await page.evaluate(async (keys) => {
  for (const k of keys) {
    const f = new FontFace(`oracle-${k}`, `url(/fonts/${k})`);
    await f.load();
    document.fonts.add(f);
  }
}, Object.keys(fonts));

const results = await page.evaluate(
  ({ prepared, SIZE }) => {
    const W = 1400;
    const H = 200;
    const base = 130;
    const ink = (ctx) => {
      const d = ctx.getImageData(0, 0, W, H).data;
      const out = new Uint8Array(W * H);
      for (let i = 0; i < W * H; i++) out[i] = d[i * 4 + 3] > 127 ? 1 : 0;
      return out;
    };
    const near = (img, x, y) => {
      for (let dy = -1; dy <= 1; dy++)
        for (let dx = -1; dx <= 1; dx++) {
          const xx = x + dx;
          const yy = y + dy;
          if (xx >= 0 && yy >= 0 && xx < W && yy < H && img[yy * W + xx]) return true;
        }
      return false;
    };
    return prepared.map((c) => {
      if (c.unsupported.length) return { label: c.label, name: c.name, unsupported: c.unsupported };
      const a = document.createElement("canvas");
      const b = document.createElement("canvas");
      a.width = b.width = W;
      a.height = b.height = H;
      const ca = a.getContext("2d");
      const cb = b.getContext("2d");
      // Browser rendering with the same font stack (per-run fonts via fallback list).
      ca.font = `${SIZE}px ${c.fontKeys.map((k) => `"oracle-${k}"`).join(", ")}`;
      ca.textAlign = "left";
      // Paragraph direction from the first strong character, as the shaper does (dir="auto").
      ca.direction = /^[^A-Za-z\u00C0-\u024F\u0370-\u03FF\u0400-\u04FF\u0590-\u08FF]*[\u0590-\u08FF]/.test(c.name) ? "rtl" : "ltr";
      ca.fillStyle = "#000";
      ca.fillText(c.name, 20, base);
      const browserWidth = ca.measureText(c.name).width;
      cb.fillStyle = "#000";
      for (const g of c.glyphs) {
        cb.save();
        cb.translate(20 + g.x, base - g.y);
        cb.fill(new Path2D(g.d));
        cb.restore();
      }
      const ia = ink(ca);
      const ib = ink(cb);
      let total = 0;
      let miss = 0;
      for (let y = 0; y < H; y++)
        for (let x = 0; x < W; x++) {
          const p = y * W + x;
          if (ia[p] || ib[p]) total++;
          if ((ia[p] && !near(ib, x, y)) || (ib[p] && !near(ia, x, y))) miss++;
        }
      return { label: c.label, name: c.name, mismatch: total ? miss / total : 0, browserWidth, ourWidth: c.width, pngA: a.toDataURL(), pngB: b.toDataURL() };
    });
  },
  { prepared, SIZE },
);
await browser.close();

const THRESHOLD = 0.02;
let failed = 0;
const report = [];
for (const r of results) {
  const c = cases.find((x) => x.label === r.label);
  const ok = !r.unsupported && r.mismatch <= THRESHOLD && Math.abs(r.browserWidth - r.ourWidth) <= 1.5;
  const expectedUnsupported = c.expect === "unsupported";
  const pass = expectedUnsupported ? Boolean(r.unsupported) : ok;
  if (!pass) failed++;
  report.push({ label: r.label, name: r.name, pass, mismatch: r.mismatch, browserWidth: r.browserWidth, ourWidth: r.ourWidth, unsupported: r.unsupported });
  console.log(`${pass ? "✔" : "✖"} ${r.label.padEnd(26)} ${r.unsupported ? `unsupported (${r.unsupported.join(",")})` : `mismatch ${(r.mismatch * 100).toFixed(2)}%  width ${r.ourWidth.toFixed(1)} vs ${r.browserWidth.toFixed(1)}`}  ${r.name}`);
  if (imagesDir && r.pngA) {
    writeFileSync(join(imagesDir, `${r.label}-browser.png`), Buffer.from(r.pngA.split(",")[1], "base64"));
    writeFileSync(join(imagesDir, `${r.label}-ours.png`), Buffer.from(r.pngB.split(",")[1], "base64"));
  }
}
if (opt("--out")) writeFileSync(opt("--out"), JSON.stringify(report, null, 2));
console.log(`\n${results.length - failed}/${results.length} names match the browser's shaping`);
process.exit(failed ? 1 : 0);
