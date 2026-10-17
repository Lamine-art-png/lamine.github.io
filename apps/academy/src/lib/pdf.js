// Minimal PDF 1.4 writer (standard-14 fonts, WinAnsi text, vector drawing,
// one embedded JPEG) and the AGRO-AI Academy certificate layout.
import { WIDTHS } from "./font-metrics.js";
import { MARK_JPEG_B64, MARK_JPEG_SIZE } from "./brand-jpeg.js";
import { encodeQr } from "./qr.js";
import { b64urlDecode } from "./util.js";

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
  text(str, x, y, { font = "Helvetica", size = 12, color = "#10231b", align = "left", charSpace = 0, maxWidth = 0 } = {}) {
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
  const content = canvas.ops.join("\n");
  const fonts = Object.entries(FONT_KEYS);
  const fontObjBase = 7;
  write("%PDF-1.4\n%\xe2\xe3\xcf\xd3\n");
  obj(1, "<< /Type /Catalog /Pages 2 0 R >>");
  obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>");
  obj(
    3,
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${width} ${height}] /Contents 4 0 R /Resources << /Font << ${fonts
      .map(([, key], i) => `/${key} ${fontObjBase + i} 0 R`)
      .join(" ")} >> /XObject << /Im1 5 0 R >> /ProcSet [/PDF /Text /ImageC] >> >>`,
  );
  obj(4, [`<< /Length ${enc.encode(content).length} >>\nstream\n`, content, "\nendstream"]);
  obj(5, [`<< /Type /XObject /Subtype /Image /Width ${jpeg.size} /Height ${jpeg.size} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.bytes.length} >>\nstream\n`, jpeg.bytes, "\nendstream"]);
  const info = (s) => pdfString(winAnsi(s).codes);
  obj(6, `<< /Title ${info(title)} /Subject ${info(subject)} /Author (AGRO-AI Academy) /Creator (AGRO-AI Academy) /Producer (AGRO-AI Academy credential service) >>`);
  fonts.forEach(([name], i) => obj(fontObjBase + i, `<< /Type /Font /Subtype /Type1 /BaseFont /${name} /Encoding /WinAnsiEncoding >>`));
  const count = fontObjBase + fonts.length;
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

const markJpeg = () => {
  const b64 = MARK_JPEG_B64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return { bytes: b64urlDecode(b64), size: MARK_JPEG_SIZE };
};

/**
 * Render the official certificate (A4 landscape). The credential is issued in
 * English, its canonical language; `labels` allows localized UI copies later.
 */
export function certificatePdf(cert, { verifyUrl, host, issuedDate }) {
  const W = 842;
  const H = 595;
  const cv = new Canvas();
  const green = "#1f3d27";
  const ink = "#10231b";
  const muted = "#5d6c62";
  const lime = "#8db300";
  const limeText = "#4b6b06";

  cv.fill("#fffdf8").rect(0, 0, W, H);
  cv.stroke(green, 1.6).rect(22, 22, W - 44, H - 44, "S");
  cv.stroke(lime, 0.6).rect(30, 30, W - 60, H - 60, "S");
  // Corner ornaments.
  for (const [x, y, dx, dy] of [[30, 30, 1, 1], [W - 30, 30, -1, 1], [30, H - 30, 1, -1], [W - 30, H - 30, -1, -1]]) {
    cv.stroke(green, 1.2).line(x + dx * 8, y + dy * 8, x + dx * 40, y + dy * 8).line(x + dx * 8, y + dy * 8, x + dx * 8, y + dy * 40);
  }

  // Header.
  cv.image("Im1", 64, H - 104, 40, 40);
  cv.text("AGRO-AI", 114, H - 82, { font: "Helvetica-Bold", size: 17, color: ink, charSpace: 0.6 });
  cv.text("Academy", 194, H - 82, { font: "Times-Roman", size: 19, color: ink });
  cv.text("A learning institution of AGRO-AI Inc.", 114, H - 98, { font: "Helvetica", size: 8.5, color: muted });
  cv.text("CREDENTIAL ID", W - 64, H - 74, { font: "Helvetica-Bold", size: 7.5, color: muted, align: "right", charSpace: 1.2 });
  cv.text(cert.credential_id, W - 64, H - 90, { font: "Courier", size: 11, color: ink, align: "right" });

  // Body.
  const cx = W / 2;
  cv.text("CERTIFICATE OF COMPLETION", cx, H - 168, { font: "Helvetica-Bold", size: 12, color: limeText, align: "center", charSpace: 3.2 });
  cv.stroke(lime, 0.8).line(cx - 36, H - 182, cx + 36, H - 182);
  cv.text("This certifies that", cx, H - 214, { font: "Times-Italic", size: 15, color: muted, align: "center" });
  cv.text(cert.credential_name, cx, H - 262, { font: "Times-Bold", size: 40, color: ink, align: "center", maxWidth: 660 });
  cv.text("has successfully completed the course and passed its final assessment", cx, H - 296, { font: "Helvetica", size: 12, color: "#3c4e43", align: "center" });
  const titleLines = cv.wrap(cert.course_title, "Times-Bold", 26, 640).slice(0, 2);
  titleLines.forEach((line, i) => cv.text(line, cx, H - 338 - i * 30, { font: "Times-Bold", size: 26, color: green, align: "center", maxWidth: 680 }));
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
  cv.text("AGRO-AI Academy", 250, fy + 6, { font: "Times-Bold", size: 14, color: ink });
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
    jpeg: markJpeg(),
    title: `${cert.course_title} - AGRO-AI Academy Certificate`,
    subject: `Credential ${cert.credential_id} issued to ${cert.credential_name}`,
  });
}
