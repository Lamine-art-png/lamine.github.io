// Unicode certificate names: shaping regressions against the browser-verified
// fixture, bidi helpers, font subsetting, and the PDF's embedded fonts and text.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { Font, subsetFont } from "../../src/lib/ttf.js";
import { bidiLevels, visualOrder, itemize } from "../../src/lib/shape.js";
import { unsupportedNameScripts } from "../../src/lib/pdf.js";
import { renderCertificatePdf } from "../../src/services/certificate-pdf.js";
import { assetsBinding } from "../../dev/server.js";
import { shapeForGolden } from "../../scripts/shaping-golden.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const golden = JSON.parse(readFileSync(join(root, "tests/fixtures/shaping-golden.json"), "utf8"));
const env = { ASSETS: assetsBinding(join(root, "public")) };
const opts = { verifyUrl: "https://academy.agroai-pilot.com/verify/AGA-7K2M-9QXD-4TRP", host: "academy.agroai-pilot.com", issuedDate: "October 29, 2026" };
const certFor = (name) => ({ credential_id: "AGA-7K2M-9QXD-4TRP", credential_name: name, course_title: "Introduction to Artificial Intelligence in Agriculture", program_title: null, issued_at: "2026-10-29T10:00:00Z" });
const latin1 = (bytes) => new TextDecoder("latin1").decode(bytes);
const utf16hex = (s) => [...s].map((c) => c.codePointAt(0).toString(16).padStart(4, "0")).join("").toUpperCase();

test("shaping matches the browser-verified fixture for every sample name", () => {
  const labels = Object.keys(golden);
  assert.ok(labels.length >= 100);
  for (const label of labels) {
    const want = golden[label];
    const got = shapeForGolden(want.name);
    assert.deepEqual(got, { glyphs: want.glyphs, width: want.width, unsupported: want.unsupported }, label);
  }
});

test("Hindi reorders the i-matra and forms the reph", () => {
  const g = golden["hindi-priya"].glyphs;
  // प्रिया: the pre-base i-matra glyph is drawn first (leftmost).
  assert.ok(g[0][2] === 0 && g.length < [..."प्रिया शर्मा"].length, "fewer glyphs than characters (conjuncts and reph)");
});

test("bidi: Arabic is right-to-left, Latin and digits keep their order", () => {
  const cps = [..."Ahmed أحمد 12"].map((c) => c.codePointAt(0));
  const levels = bidiLevels(cps);
  assert.equal(levels[0], 0);
  assert.equal(levels[6], 1);
  assert.deepEqual(visualOrder([0, 0, 1, 1, 1]), [0, 1, 4, 3, 2]);
  assert.deepEqual(visualOrder([1, 1, 2, 2, 1]), [4, 2, 3, 1, 0]);
  assert.deepEqual([...new Set(itemize("Zoë محمد").map((c) => c.script))], ["latn", "arab"]);
});

test("unsupported writing systems are detected before rendering", () => {
  assert.deepEqual(unsupportedNameScripts("Nguyễn Thị Minh Khai"), []);
  assert.deepEqual(unsupportedNameScripts("王小明"), []);
  assert.deepEqual(unsupportedNameScripts("वెంకటేశ్వర".slice(1)), ["telu"]);
  assert.deepEqual(unsupportedNameScripts("အောင်ဆန်း"), ["mymr"]);
});

test("font subsets keep only the used glyphs and remain valid TrueType", () => {
  const font = new Font(readFileSync(join(root, "public/static/fonts/pdf/FreeSerifBold.ttf")));
  const gids = [font.glyphForCodePoint(0x915), font.glyphForCodePoint(0x94d), font.glyphForCodePoint(0x937)];
  const { bytes, newId } = subsetFont(font, gids);
  const sub = new Font(bytes);
  assert.ok(sub.numGlyphs <= 10 && sub.numGlyphs >= 4, `${sub.numGlyphs} glyphs`);
  assert.ok(bytes.length < 20000, `${bytes.length} bytes (hinting and name tables included)`);
  for (const g of gids) {
    assert.equal(sub.advance(newId.get(g)), font.advance(g));
    assert.deepEqual(sub.contours(newId.get(g)), font.contours(g));
  }
});

for (const [label, name, fontName] of [
  ["Arabic", "محمد عبد الله", "DejaVuSans-Bold"],
  ["Chinese", "王小明", "WenQuanYiZenHei"],
  ["Hindi", "प्रिया शर्मा", "FreeSerifBold"],
  ["accented Latin", "Nguyễn Thị Minh Khai", "DejaVuSerif-Bold"],
]) {
  test(`certificate PDF embeds a font subset and real text for a ${label} name`, async () => {
    const pdf = await renderCertificatePdf(env, "https://academy.test", certFor(name), opts);
    const s = latin1(pdf);
    assert.equal(s.slice(0, 8), "%PDF-1.4");
    assert.match(s, new RegExp(`/BaseFont /[A-Z]{6}\\+${fontName} /Encoding /Identity-H`));
    assert.match(s, /\/Subtype \/CIDFontType2/);
    assert.match(s, /\/FontFile2 \d+ 0 R/);
    assert.match(s, /\/ToUnicode \d+ 0 R/);
    assert.doesNotMatch(s, /\(\?+\) Tj/, "no question-mark substitutes");
    // The document metadata carries the exact name.
    assert.ok(s.includes(`<FEFF${utf16hex(`Credential AGA-7K2M-9QXD-4TRP issued to ${name}`)}>`));
    // Left-to-right names carry ActualText; right-to-left ones map every glyph to Unicode.
    if (label === "Arabic") for (const ch of "محمدعبلاه") assert.ok(s.includes(`<${ch.codePointAt(0).toString(16).padStart(4, "0").toUpperCase()}>`), `ToUnicode has ${ch}`);
    else assert.ok(s.includes(`/ActualText <FEFF${utf16hex(name.split(" ")[0])}>`));
    // The embedded subset parses and is small.
    const m = /\/Length (\d+) \/Length1 \d+ >>\nstream\n/.exec(s);
    const start = m.index + m[0].length;
    const sub = new Font(pdf.slice(start, start + Number(m[1])));
    assert.ok(sub.numGlyphs > 2 && sub.numGlyphs < 80, `${sub.numGlyphs} glyphs embedded`);
    assert.ok(pdf.length < 120000, `${pdf.length} bytes`);
  });
}

test("Windows-1252 names keep the standard Times-Bold rendering", async () => {
  const s = latin1(await renderCertificatePdf(env, "https://academy.test", certFor("María José Ñúñez"), opts));
  assert.doesNotMatch(s, /CIDFontType2/);
  assert.match(s, /\(Mar\\355a Jos\\351 \\321\\372\\361ez\) Tj/);
});

test("a name in an unsupported script is refused rather than printed wrongly", async () => {
  await assert.rejects(renderCertificatePdf(env, "https://academy.test", certFor("వెంకటేశ్వర"), opts), /name_script_unsupported/);
});
