// QR encoder verified by an independent decoder built from the ISO/IEC 18004
// tables (alignment positions, block structure), and PDF structure checks.
import { test } from "node:test";
import assert from "node:assert/strict";
import { encodeQr } from "../../src/lib/qr.js";
import { certificatePdf, winAnsi } from "../../src/lib/pdf.js";

// ISO/IEC 18004 Annex E alignment pattern centers, versions 1–10.
const ALIGN = { 1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50] };
// ISO table 9, level M: [total codewords, ecc per block, blocks group1, data per block g1, blocks group2, data per block g2]
const BLOCKS_M = { 1: [26, 10, 1, 16, 0, 0], 2: [44, 16, 1, 28, 0, 0], 3: [70, 26, 1, 44, 0, 0], 4: [100, 18, 2, 32, 0, 0], 5: [134, 24, 2, 43, 0, 0], 6: [172, 16, 4, 27, 0, 0], 7: [196, 18, 4, 31, 0, 0], 8: [242, 22, 2, 38, 2, 39], 9: [292, 22, 3, 36, 2, 37], 10: [346, 26, 4, 43, 1, 44] };

function gfMul(a, b) {
  let r = 0;
  while (b) {
    if (b & 1) r ^= a;
    a = (a << 1) ^ (a & 0x80 ? 0x11d : 0);
    b >>= 1;
  }
  return r & 0xff;
}
function syndromesZero(block, ecc) {
  let alpha = 1;
  for (let i = 0; i < ecc; i++) {
    let s = 0;
    for (const c of block) s = gfMul(s, alpha) ^ c;
    if (s !== 0) return false;
    alpha = gfMul(alpha, 2);
  }
  return true;
}

function decode(modules) {
  const size = modules.length;
  const ver = (size - 17) / 4;
  const fn = Array.from({ length: size }, () => new Array(size).fill(false));
  const mark = (x, y) => x >= 0 && y >= 0 && x < size && y < size && (fn[y][x] = true);
  for (const [cx, cy] of [[0, 0], [size - 8, 0], [0, size - 8]]) for (let dy = 0; dy < 8; dy++) for (let dx = 0; dx < 8; dx++) mark(cx + dx, cy + dy);
  for (let i = 0; i < size; i++) {
    mark(6, i);
    mark(i, 6);
  }
  const al = ALIGN[ver];
  for (const ax of al) for (const ay of al) {
    if ((ax === 6 && ay === 6) || (ax === 6 && ay === al[al.length - 1]) || (ax === al[al.length - 1] && ay === 6)) continue;
    for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) mark(ax + dx, ay + dy);
  }
  for (let i = 0; i < 9; i++) {
    mark(8, i);
    mark(i, 8);
  }
  for (let i = 0; i < 8; i++) {
    mark(size - 1 - i, 8);
    mark(8, size - 1 - i);
  }
  if (ver >= 7) for (let a = 0; a < 6; a++) for (let b = size - 11; b < size - 8; b++) {
    mark(a, b);
    mark(b, a);
  }
  // Format information (first copy) → error level and mask.
  let fmt = 0;
  const fbits = [];
  for (let i = 0; i <= 5; i++) fbits.push(modules[i][8]);
  fbits.push(modules[7][8], modules[8][8], modules[8][7]);
  for (let i = 9; i < 15; i++) fbits.push(modules[8][14 - i]);
  fbits.forEach((b, i) => (fmt |= (b ? 1 : 0) << i));
  fmt ^= 0x5412;
  const ecl = fmt >> 13;
  const mask = (fmt >> 10) & 7;
  assert.equal(ecl, 0, "error correction level M");
  const masks = [(x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, (x) => x % 3 === 0, (x, y) => (x + y) % 3 === 0, (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0, (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0, (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0, (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0];
  const bits = [];
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let v = 0; v < size; v++) for (let j = 0; j < 2; j++) {
      const x = right - j;
      const y = ((right + 1) & 2) === 0 ? size - 1 - v : v;
      if (!fn[y][x]) bits.push(modules[y][x] !== masks[mask](x, y));
    }
  }
  const [total, ecc, g1, d1, g2, d2] = BLOCKS_M[ver];
  const cw = [];
  for (let i = 0; i < total * 8; i += 8) cw.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | (b ? 1 : 0), 0));
  const lens = [...Array(g1).fill(d1), ...Array(g2).fill(d2)];
  const blocks = lens.map(() => []);
  let k = 0;
  for (let i = 0; i < Math.max(...lens); i++) lens.forEach((len, b) => i < len && blocks[b].push(cw[k++]));
  for (let i = 0; i < ecc; i++) blocks.forEach((blk) => blk.push(cw[k++]));
  blocks.forEach((blk, i) => assert.ok(syndromesZero(blk, ecc), `block ${i} passes Reed–Solomon check`));
  const data = blocks.flatMap((blk, i) => blk.slice(0, lens[i]));
  const dbits = data.flatMap((b) => [7, 6, 5, 4, 3, 2, 1, 0].map((s) => (b >> s) & 1));
  let p = 0;
  const read = (n) => {
    let v = 0;
    for (let i = 0; i < n; i++) v = (v << 1) | dbits[p++];
    return v;
  };
  assert.equal(read(4), 0b0100, "byte mode");
  const len = read(ver < 10 ? 8 : 16);
  const out = [];
  for (let i = 0; i < len; i++) out.push(read(8));
  return new TextDecoder().decode(new Uint8Array(out));
}

test("QR codes decode correctly across versions 1–10", () => {
  const samples = [
    "hi",
    "https://academy.agroai-pilot.com/verify/AGA-7K2M-9QXD-4TRP",
    "https://academy-staging.agroai-pilot.com/verify/AGA-ABCD-EFGH-JKMN?utm=linkedin",
    "x".repeat(120),
    "AGRO-AI Academy · Ünïcödé ✓ " + "y".repeat(150),
  ];
  const versions = new Set();
  for (const s of samples) {
    const qr = encodeQr(s);
    versions.add(qr.version);
    assert.equal(decode(qr.modules), s);
  }
  assert.ok(versions.has(1) && [...versions].some((v) => v >= 7), `covers small and version-info sizes (${[...versions]})`);
  assert.throws(() => encodeQr("z".repeat(300)), /too long/);
});

test("certificate PDF is a well-formed single-page PDF", () => {
  const cert = { credential_id: "AGA-7K2M-9QXD-4TRP", credential_name: "Nguyễn Văn An", course_title: "Introduction to Artificial Intelligence in Agriculture (A very long title that wraps)", program_title: "Foundations of Agricultural AI", issued_at: "2026-10-29T00:00:00Z" };
  const pdf = certificatePdf(cert, { verifyUrl: "https://academy.agroai-pilot.com/verify/AGA-7K2M-9QXD-4TRP", host: "academy.agroai-pilot.com", issuedDate: "October 29, 2026" });
  const text = new TextDecoder("latin1").decode(pdf);
  assert.ok(text.startsWith("%PDF-1.4"));
  assert.ok(text.trimEnd().endsWith("%%EOF"));
  const xref = Number(/startxref\n(\d+)/.exec(text)[1]);
  assert.equal(text.slice(xref, xref + 4), "xref", "startxref points at the xref table");
  for (const m of text.matchAll(/(\d{10}) 00000 n /g)) {
    const off = Number(m[1]);
    assert.match(text.slice(off, off + 12), /^\d+ 0 obj/, "xref offsets point at objects");
  }
  assert.match(text, /\/Count 1/);
  assert.match(text, /\/Filter \/DCTDecode/);
  assert.match(text, /AGA-7K2M-9QXD-4TRP/);
  // Vietnamese diacritics outside WinAnsi degrade to base letters rather than failing.
  assert.equal(winAnsi("Nguyễn").lossy, true);
  assert.equal(winAnsi("Gonçalves").lossy, false);
});
