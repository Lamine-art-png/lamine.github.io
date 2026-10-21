// Minimal PDF 1.4 writer (standard-14 fonts, WinAnsi text, vector drawing,
// one embedded JPEG, embedded TrueType subsets for shaped Unicode text) and
// the AGRO-AI Academy certificate layout.
import { WIDTHS } from "./font-metrics.js";
import { LOCKUP_JPEG_B64, LOCKUP_JPEG_WIDTH, LOCKUP_JPEG_HEIGHT } from "./brand-jpeg.js";
import { BRAND } from "../brand.js";
import { encodeQr } from "./qr.js";
import { b64urlDecode } from "./util.js";
import { subsetFont } from "./ttf.js";
import { itemize } from "./shape.js";
import { fontKeysFor } from "./name-fonts.js";

const CP1252_EXTRA = {
  0x20ac: 0x80, 0x201a: 0x82, 0x0192: 0x83, 0x201e: 0x84, 0x2026: 0x85, 0x2020: 0x86, 0x2021: 0x87, 0x02c6: 0x88, 0x2030: 0x89,
  0x0160: 0x8a, 0x2039: 0x8b, 0x0152: 0x8c, 0x017d: 0x8e, 0x2018: 0x91, 0x2019: 0x92, 0x201c: 0x93, 0x201d: 0x94, 0x2022: 0x95,
  0x2013: 0x96, 0x2014: 0x97, 0x02dc: 0x98, 0x2122: 0x99, 0x0161: 0x9a, 0x203a: 0x9b, 0x0153: 0x9c, 0x017e: 0x9e, 0x0178: 0x9f,
};

function charCode(cp) {
  if (cp >= 0x20 && cp < 0x7f) return cp;
  if (cp >= 0xa0 && cp <= 0xff) return cp;
  return CP1252_EXTRA[cp] ?? null;
}

/** Encode text as WinAnsi codes. Unsupported letters lose diacritics first; anything else becomes "?". */
export function winAnsi(text) {
  const codes = [];
  let lossy = false;
  for (const ch of String(text)) {
    let c = charCode(ch.codePointAt(0));
    if (c == null) {
      const base = ch.normalize("NFKD").replace(/[̀-ͯ]/g, "");
      const parts = [...base].map((b) => charCode(b.codePointAt(0)));
      if (base && parts.every((p) => p != null)) codes.push(...parts);
      else codes.push(0x3f);
      lossy = true;
      continue;
    }
    codes.push(c);
  }
  return { codes, lossy };
}

export const pdfRepresentable = (text) => !winAnsi(text).lossy;

/** Scripts in `text` that no certificate font covers (empty when the PDF can print it). */
export function unsupportedNameScripts(text) {
  const scripts = new Set(itemize(String(text)).map((c) => (c.script === "zyyy" ? "latn" : c.script)));
  return [...scripts].filter((sc) => !fontKeysFor(sc).length);
}

/** PDF text string: literal for WinAnsi text, UTF-16BE (with BOM) otherwise. */
function pdfTextString(text) {
  const w = winAnsi(text);
  if (!w.lossy) return pdfString(w.codes);
  let hex = "FEFF";
  for (const ch of String(text)) {
    const cp = ch.codePointAt(0);
    if (cp > 0xffff) {
      const v = cp - 0x10000;
      hex += (0xd800 + (v >> 10)).toString(16).padStart(4, "0") + (0xdc00 + (v & 0x3ff)).toString(16).padStart(4, "0");
    } else hex += cp.toString(16).padStart(4, "0");
  }
  return `<${hex.toUpperCase()}>`;
}

function textWidth(codes, font, size, charSpace = 0) {
  const w = WIDTHS[font];
  return codes.reduce((s, c) => s + (c >= 32 ? w[c - 32] || 500 : 0), 0) * (size / 1000) + charSpace * codes.length;
}

function pdfString(codes) {
  let s = "(";
  for (const c of codes) {
    if (c === 0x28 || c === 0x29 || c === 0x5c) s += "\\" + String.fromCharCode(c);
    else if (c < 0x20 || c > 0x7e) s += "\\" + c.toString(8).padStart(3, "0");
    else s += String.fromCharCode(c);
  }
  return s + ")";
}

const FONT_KEYS = { Helvetica: "F1", "Helvetica-Bold": "F2", "Times-Roman": "F3", "Times-Bold": "F4", "Times-Italic": "F5", Courier: "F6" };
const rgb = (hex) => [1, 3, 5].map((i) => (parseInt(hex.slice(i, i + 2), 16) / 255).toFixed(3)).join(" ");
const n = (v) => (Math.round(v * 100) / 100).toString();

class Canvas {
  constructor() {
    this.ops = [];
    /** Embedded fonts: Font → Map(gid → text) of glyphs used. */
    this.embedded = new Map();
  }
  /**
   * Draw a shaped line (from shapeLine at `size`). Glyph ids are resolved to
   * subset ids when the PDF is assembled. ActualText carries the exact text
   * for copy, search and screen readers.
   */
  shaped(line, text, x, y, { size, color = "#0f2410", align = "left", maxWidth = 0 }) {
    let k = 1;
    if (maxWidth && line.width > maxWidth) k = maxWidth / line.width;
    const w = line.width * k;
    const ox = align === "center" ? x - w / 2 : align === "right" ? x - w : x;
    for (const g of line.glyphs) {
      if (!this.embedded.has(g.font)) this.embedded.set(g.font, new Map());
      const used = this.embedded.get(g.font);
      if (!used.has(g.gid)) used.set(g.gid, g.text);
    }
    // Glyphs are written run by run in reading order, each at its own position.
    // Left-to-right runs (where Indic reordering and ligatures break glyph-by-
    // glyph extraction) carry their text as ActualText; right-to-left runs are
    // extracted from the ToUnicode map, which viewers reorder themselves.
    const glyphs = [...line.glyphs].sort((a, b) => a.logical - b.logical);
    const runs = line.runs || [{ text, rtl: false }];
    this.ops.push((fonts) => {
      let out = `BT ${rgb(color)} rg`;
      let current = null;
      let open = -1;
      for (const g of glyphs) {
        const run = g.run ?? 0;
        if (run !== open) {
          if (open >= 0 && !runs[open].rtl) out += " EMC";
          if (!runs[run].rtl) out += ` /Span << /ActualText ${pdfTextString(runs[run].text)} >> BDC`;
          open = run;
        }
        const f = fonts.get(g.font);
        if (current !== f.key) {
          out += ` /${f.key} ${n(size * k)} Tf`;
          current = f.key;
        }
        out += ` 1 0 0 1 ${n(ox + g.x * k)} ${n(y + g.y * k)} Tm <${f.newId.get(g.gid).toString(16).padStart(4, "0")}> Tj`;
      }
      if (open >= 0 && !runs[open].rtl) out += " EMC";
      return `${out} ET`;
    });
    return size * k;
  }
  fill(hex) {
    this.ops.push(`${rgb(hex)} rg`);
    return this;
  }
  stroke(hex, width = 1) {
    this.ops.push(`${rgb(hex)} RG ${n(width)} w`);
    return this;
  }
  rect(x, y, w, h, mode = "f") {
    this.ops.push(`${n(x)} ${n(y)} ${n(w)} ${n(h)} re ${mode}`);
    return this;
  }
  line(x1, y1, x2, y2) {
    this.ops.push(`${n(x1)} ${n(y1)} m ${n(x2)} ${n(y2)} l S`);
    return this;
  }
  image(name, x, y, w, h) {
    this.ops.push(`q ${n(w)} 0 0 ${n(h)} ${n(x)} ${n(y)} cm /${name} Do Q`);
    return this;
  }
  /** Draw text; align: left|center|right. Shrinks to maxWidth when given. Returns the size used. */
  text(str, x, y, { font = "Helvetica", size = 12, color = "#0f2410", align = "left", charSpace = 0, maxWidth = 0 } = {}) {
    const { codes } = winAnsi(str);
    let s = size;
    let w = textWidth(codes, font, s, charSpace);
    if (maxWidth && w > maxWidth) {
      s = Math.max(7, (s * maxWidth) / w);
      w = textWidth(codes, font, s, charSpace);
    }
    const tx = align === "center" ? x - w / 2 : align === "right" ? x - w : x;
    this.ops.push(`BT /${FONT_KEYS[font]} ${n(s)} Tf ${n(charSpace)} Tc ${rgb(color)} rg ${n(tx)} ${n(y)} Td ${pdfString(codes)} Tj ET`);
    return s;
  }
  /** Greedy word wrap; returns the lines. */
  wrap(str, font, size, maxWidth) {
    const words = String(str).split(/\s+/);
    const lines = [];
    let cur = "";
    for (const word of words) {
      const next = cur ? `${cur} ${word}` : word;
      if (cur && textWidth(winAnsi(next).codes, font, size) > maxWidth) {
        lines.push(cur);
        cur = word;
      } else cur = next;
    }
    if (cur) lines.push(cur);
    return lines;
  }
}

/** Assemble a single-page PDF with the given canvas and optional JPEG XObject. */
function buildPdf(canvas, { width, height, jpeg, title, subject }) {
  const enc = new TextEncoder();
  const chunks = [];
  const offsets = [];
  let length = 0;
  const write = (data) => {
    const bytes = typeof data === "string" ? enc.encode(data) : data;
    chunks.push(bytes);
    length += bytes.length;
  };
  const obj = (id, body) => {
    offsets[id] = length;
    write(`${id} 0 obj\n`);
    for (const part of [].concat(body)) write(part);
    write("\nendobj\n");
  };
  const fonts = Object.entries(FONT_KEYS);
  const fontObjBase = 7;
  // Embedded TrueType subsets: 5 objects each, after the standard fonts.
  const embedded = new Map();
  let nextObj = fontObjBase + fonts.length;
  let e = 0;
  for (const [font, used] of canvas.embedded) {
    const { bytes, newId } = subsetFont(font, [...used.keys()]);
    embedded.set(font, { key: `E${++e}`, font, used, bytes, newId, obj: nextObj });
    nextObj += 5;
  }
  const content = canvas.ops.map((op) => (typeof op === "function" ? op(embedded) : op)).join("\n");
  write("%PDF-1.4\n%\xe2\xe3\xcf\xd3\n");
  obj(1, "<< /Type /Catalog /Pages 2 0 R >>");
  obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>");
  obj(
    3,
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${width} ${height}] /Contents 4 0 R /Resources << /Font << ${fonts
      .map(([, key], i) => `/${key} ${fontObjBase + i} 0 R`)
      .concat([...embedded.values()].map((f) => `/${f.key} ${f.obj} 0 R`))
      .join(" ")} >> /XObject << /Im1 5 0 R >> /ProcSet [/PDF /Text /ImageC] >> >>`,
  );
  obj(4, [`<< /Length ${enc.encode(content).length} >>\nstream\n`, content, "\nendstream"]);
  obj(5, [`<< /Type /XObject /Subtype /Image /Width ${jpeg.width} /Height ${jpeg.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.bytes.length} >>\nstream\n`, jpeg.bytes, "\nendstream"]);
  obj(6, `<< /Title ${pdfTextString(title)} /Subject ${pdfTextString(subject)} /Author (AGRO-AI Academy) /Creator (AGRO-AI Academy) /Producer (AGRO-AI Academy credential service) >>`);
  fonts.forEach(([name], i) => obj(fontObjBase + i, `<< /Type /Font /Subtype /Type1 /BaseFont /${name} /Encoding /WinAnsiEncoding >>`));
  for (const f of embedded.values()) {
    const scale = 1000 / f.font.unitsPerEm;
    const tag = subsetTag(f.bytes);
    const base = `${tag}+${f.font.name}`;
    const order = [...f.newId].sort((a, b) => a[1] - b[1]);
    const widths = order.map(([old]) => Math.round(f.font.advance(old) * scale)).join(" ");
    const bbox = f.font.bbox.map((v) => Math.round(v * scale)).join(" ");
    obj(f.obj, `<< /Type /Font /Subtype /Type0 /BaseFont /${base} /Encoding /Identity-H /DescendantFonts [${f.obj + 1} 0 R] /ToUnicode ${f.obj + 4} 0 R >>`);
    obj(f.obj + 1, `<< /Type /Font /Subtype /CIDFontType2 /BaseFont /${base} /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /FontDescriptor ${f.obj + 2} 0 R /CIDToGIDMap /Identity /W [0 [${widths}]] >>`);
    obj(
      f.obj + 2,
      `<< /Type /FontDescriptor /FontName /${base} /Flags 4 /FontBBox [${bbox}] /ItalicAngle 0 /Ascent ${Math.round(f.font.ascender * scale)} /Descent ${Math.round(f.font.descender * scale)} /CapHeight ${Math.round(f.font.capHeight * scale)} /StemV 80 /FontFile2 ${f.obj + 3} 0 R >>`,
    );
    obj(f.obj + 3, [`<< /Length ${f.bytes.length} /Length1 ${f.bytes.length} >>\nstream\n`, f.bytes, "\nendstream"]);
    const cmap = toUnicodeCMap(order.map(([old, nw]) => [nw, f.used.get(old) || ""]));
    obj(f.obj + 4, [`<< /Length ${enc.encode(cmap).length} >>\nstream\n`, cmap, "\nendstream"]);
  }
  const count = nextObj;
  const xref = length;
  let table = `xref\n0 ${count}\n0000000000 65535 f \n`;
  for (let i = 1; i < count; i++) table += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`;
  write(table);
  write(`trailer\n<< /Size ${count} /Root 1 0 R /Info 6 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
  const out = new Uint8Array(length);
  let o = 0;
  for (const c of chunks) {
    out.set(c, o);
    o += c.length;
  }
  return out;
}

/** Six-letter subset tag derived from the subset's bytes (PDF 9.6.4). */
function subsetTag(bytes) {
  let h = 2166136261;
  for (let i = 0; i < bytes.length; i += 7) h = Math.imul(h ^ bytes[i], 16777619) >>> 0;
  let tag = "";
  for (let i = 0; i < 6; i++) {
    tag += String.fromCharCode(65 + (h % 26));
    h = (Math.floor(h / 26) ^ Math.imul(i + 1, 2654435761)) >>> 0;
  }
  return tag;
}

/** ToUnicode CMap mapping glyph ids (CIDs) to the text they represent. */
function toUnicodeCMap(entries) {
  const utf16 = (str) =>
    [...str]
      .map((ch) => {
        const cp = ch.codePointAt(0);
        if (cp <= 0xffff) return cp.toString(16).padStart(4, "0");
        const v = cp - 0x10000;
        return (0xd800 + (v >> 10)).toString(16) + (0xdc00 + (v & 0x3ff)).toString(16);
      })
      .join("")
      .toUpperCase();
  const lines = entries.filter(([, t]) => t).map(([cid, t]) => `<${cid.toString(16).padStart(4, "0").toUpperCase()}> <${utf16(t)}>`);
  const chunks = [];
  for (let i = 0; i < lines.length; i += 100) chunks.push(`${Math.min(100, lines.length - i)} beginbfchar\n${lines.slice(i, i + 100).join("\n")}\nendbfchar`);
  return [
    "/CIDInit /ProcSet findresource begin",
    "12 dict begin",
    "begincmap",
    "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
    "/CMapName /Adobe-Identity-UCS def",
    "/CMapType 2 def",
    "1 begincodespacerange",
    "<0000> <FFFF>",
    "endcodespacerange",
    ...chunks,
    "endcmap",
    "CMapName currentdict /CMap defineresource pop",
    "end",
    "end",
  ].join("\n");
}

const lockupJpeg = () => {
  const b64 = LOCKUP_JPEG_B64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return { bytes: b64urlDecode(b64), width: LOCKUP_JPEG_WIDTH, height: LOCKUP_JPEG_HEIGHT };
};

/**
 * Render the official certificate (A4 landscape). The credential is issued in
 * English, its canonical language; `labels` allows localized UI copies later.
 */
export function certificatePdf(cert, { verifyUrl, host, issuedDate, nameLine = null }) {
  const W = 842;
  const H = 595;
  const cv = new Canvas();
  const { green, ink, muted, leafBright: lime, leaf: limeText } = BRAND.colors;

  cv.fill("#fffdf8").rect(0, 0, W, H);
  cv.stroke(green, 1.6).rect(22, 22, W - 44, H - 44, "S");
  cv.stroke(lime, 0.6).rect(30, 30, W - 60, H - 60, "S");
  // Corner ornaments.
  for (const [x, y, dx, dy] of [[30, 30, 1, 1], [W - 30, 30, -1, 1], [30, H - 30, 1, -1], [W - 30, H - 30, -1, -1]]) {
    cv.stroke(green, 1.2).line(x + dx * 8, y + dy * 8, x + dx * 40, y + dy * 8).line(x + dx * 8, y + dy * 8, x + dx * 8, y + dy * 40);
  }

  // Header: the official AGRO-AI Academy lockup.
  const logoH = 46;
  cv.image("Im1", 64, H - 112, (logoH * LOCKUP_JPEG_WIDTH) / LOCKUP_JPEG_HEIGHT, logoH);
  cv.text("A learning institution of AGRO-AI Inc.", 64, H - 126, { font: "Helvetica", size: 8.5, color: muted });
  cv.text("CREDENTIAL ID", W - 64, H - 74, { font: "Helvetica-Bold", size: 7.5, color: muted, align: "right", charSpace: 1.2 });
  cv.text(cert.credential_id, W - 64, H - 90, { font: "Courier", size: 11, color: ink, align: "right" });

  // Body.
  const cx = W / 2;
  cv.text("CERTIFICATE OF COMPLETION", cx, H - 168, { font: "Helvetica-Bold", size: 12, color: limeText, align: "center", charSpace: 3.2 });
  cv.stroke(lime, 0.8).line(cx - 36, H - 182, cx + 36, H - 182);
  cv.text("This certifies that", cx, H - 214, { font: "Times-Italic", size: 15, color: muted, align: "center" });
  // Names outside Windows-1252 are shaped and set in an embedded font.
  if (nameLine) cv.shaped(nameLine, cert.credential_name, cx, H - 262, { size: 40, color: ink, align: "center", maxWidth: 660 });
  else cv.text(cert.credential_name, cx, H - 262, { font: "Times-Bold", size: 40, color: ink, align: "center", maxWidth: 660 });
  cv.text("has successfully completed the course and passed its final assessment", cx, H - 296, { font: "Helvetica", size: 12, color: "#3c4e43", align: "center" });
  const titleLines = cv.wrap(cert.course_title, "Helvetica-Bold", 24, 640).slice(0, 2);
  titleLines.forEach((line, i) => cv.text(line, cx, H - 338 - i * 30, { font: "Helvetica-Bold", size: 24, color: green, align: "center", maxWidth: 680 }));
  const descY = H - 338 - titleLines.length * 30 - 8;
  const desc = cert.program_title
    ? `Part of the ${cert.program_title} program. Awarded for verified course completion and assessment achievement within AGRO-AI Academy.`
    : "Awarded for verified course completion and assessment achievement within AGRO-AI Academy.";
  cv.wrap(desc, "Helvetica", 10, 560).forEach((line, i) => cv.text(line, cx, descY - i * 14, { font: "Helvetica", size: 10, color: muted, align: "center" }));

  // Footer: issue details, issuer, QR verification.
  const fy = 96;
  cv.text("DATE OF ISSUE", 64, fy + 22, { font: "Helvetica-Bold", size: 7.5, color: muted, charSpace: 1.2 });
  cv.text(issuedDate, 64, fy + 6, { font: "Helvetica-Bold", size: 12, color: ink });
  cv.text("AUTHORIZED ISSUER", 250, fy + 22, { font: "Helvetica-Bold", size: 7.5, color: muted, charSpace: 1.2 });
  cv.text("AGRO-AI Academy", 250, fy + 6, { font: "Helvetica-Bold", size: 13, color: ink });
  cv.text("AGRO-AI Inc., San Francisco, California", 250, fy - 8, { font: "Helvetica", size: 8.5, color: muted });
  cv.stroke("#c9cfc2", 0.6).line(64, fy - 22, 520, fy - 22);
  cv.text(`Verify this credential at ${host}/verify/${cert.credential_id}`, 64, fy - 38, { font: "Helvetica", size: 8.5, color: muted, maxWidth: 470 });
  cv.text("Certifies completion of AGRO-AI Academy coursework and assessment. Not an academic degree or accredited professional license.", 64, fy - 52, {
    font: "Helvetica",
    size: 7,
    color: muted,
    maxWidth: 520,
  });

  const { size: qn, modules } = encodeQr(verifyUrl);
  const qsize = 92;
  const qx = W - 64 - qsize;
  const qy = 54;
  const m = qsize / (qn + 2);
  cv.fill("#ffffff").rect(qx - 4, qy - 4, qsize + 8, qsize + 8);
  cv.fill(ink);
  for (let y = 0; y < qn; y++) for (let x = 0; x < qn; x++) if (modules[y][x]) cv.ops.push(`${n(qx + (x + 1) * m)} ${n(qy + (qn - y) * m)} ${n(m + 0.02)} ${n(m + 0.02)} re f`);
  cv.text("Scan to verify", qx + qsize / 2, qy + qsize + 10, { font: "Helvetica-Bold", size: 7.5, color: muted, align: "center", charSpace: 0.6 });

  return buildPdf(cv, {
    width: W,
    height: H,
    jpeg: lockupJpeg(),
    title: `${cert.course_title} - AGRO-AI Academy Certificate`,
    subject: `Credential ${cert.credential_id} issued to ${cert.credential_name}`,
  });
}
