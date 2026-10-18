// Records the shaper's output for the verified oracle names as a fixture, so
// unit tests can detect shaping regressions without a browser. Regenerate only
// after `node tests/e2e/shaping-oracle.mjs` passes:
//   node scripts/shaping-golden.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { Font } from "../src/lib/ttf.js";
import { shapeLine } from "../src/lib/shape.js";
import { NAME_FONTS, chooseNameFonts } from "../src/lib/name-fonts.js";
import { ORACLE_NAMES } from "../tests/e2e/shaping-names.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const fonts = {};
const get = (k) => (fonts[k] ??= new Font(readFileSync(join(root, "public/static/fonts/pdf", NAME_FONTS[k].file))));
export function shapeForGolden(name) {
  const line = shapeLine(name, (m) => new Map([...chooseNameFonts(m, get)].map(([s, k]) => [s, k ? get(k) : null])), 1000);
  const keyOf = (f) => Object.keys(fonts).find((k) => fonts[k] === f);
  return { glyphs: line.glyphs.map((g) => [keyOf(g.font), g.gid, Math.round(g.x), Math.round(g.y)]), width: Math.round(line.width), unsupported: line.unsupported };
}
if (import.meta.url === `file://${process.argv[1]}`) {
  const out = {};
  for (const c of ORACLE_NAMES) out[c.label] = { name: c.name, ...shapeForGolden(c.name) };
  writeFileSync(join(root, "tests/fixtures/shaping-golden.json"), JSON.stringify(out, null, 0).replace(/\},"/g, '},\n"') + "\n");
  console.log(`recorded ${Object.keys(out).length} names`);
}
