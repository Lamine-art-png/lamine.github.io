// Renders certificate PDFs for names in several writing systems with Poppler
// (an independent PDF engine) and checks that each name is drawn and that
// text extraction returns it. Requires pdftoppm and pdftotext (poppler-utils).
//   node tests/e2e/pdf-poppler.mjs [--out dir]
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { assetsBinding } from "../../dev/server.js";
import { renderCertificatePdf } from "../../src/services/certificate-pdf.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const out = process.argv.includes("--out") ? process.argv[process.argv.indexOf("--out") + 1] : mkdtempSync(join(tmpdir(), "academy-pdf-"));
const env = { ASSETS: assetsBinding(join(root, "public")) };
const NAMES = {
  arabic: "محمد عبد الله",
  chinese: "王小明",
  hindi: "प्रिया शर्मा",
  latin: "Nguyễn Thị Minh Khai",
  japanese: "山田 太郎",
  korean: "김민준",
  bengali: "রবীন্দ্রনাথ ঠাকুর",
  tamil: "செல்வராஜ்",
  thai: "สมชาย ใจดี",
  persian: "علی‌رضا محمدی",
  cyrillic: "Ольга Іваненко",
};
const strip = (s) => s.replace(/[‎‏‪-‮⁦-⁩‌‍]/g, "").replace(/\s+/g, " ").trim();
let failed = 0;
for (const [label, name] of Object.entries(NAMES)) {
  const cert = { credential_id: "AGA-7K2M-9QXD-4TRP", credential_name: name, course_title: "Introduction to Artificial Intelligence in Agriculture", program_title: null, issued_at: "2026-10-29T10:00:00Z" };
  const pdf = await renderCertificatePdf(env, "https://academy.test", cert, { verifyUrl: "https://academy.agroai-pilot.com/verify/AGA-7K2M-9QXD-4TRP", host: "academy.agroai-pilot.com", issuedDate: "October 29, 2026" });
  const file = join(out, `${label}.pdf`);
  writeFileSync(file, pdf);
  const problems = [];
  // Rendering: Poppler must render without errors and draw ink in the name band.
  try {
    execFileSync("pdftoppm", ["-r", "50", "-gray", "-singlefile", file, join(out, label)], { stdio: ["ignore", "ignore", "pipe"] });
  } catch (e) {
    problems.push(`pdftoppm failed: ${e.stderr}`);
  }
  const pgm = readFileSync(join(out, `${label}.pgm`));
  const header = /^P5\s+(\d+)\s+(\d+)\s+(\d+)\s/.exec(pgm.toString("latin1", 0, 40));
  const [w, h] = [Number(header[1]), Number(header[2])];
  const data = pgm.subarray(header[0].length);
  let ink = 0;
  for (let y = Math.round(h * 0.38); y < Math.round(h * 0.5); y++) for (let x = Math.round(w * 0.15); x < Math.round(w * 0.85); x++) if (data[y * w + x] < 128) ink++;
  if (ink < 150) problems.push(`no name drawn (${ink} dark pixels)`);
  // Text: the extracted line must equal the name (bidi controls ignored; Arabic-script
  // lines may come out in visual order with markers, so compare either order).
  const text = execFileSync("pdftotext", ["-layout", file, "-"]).toString("utf8");
  const lines = text.split("\n").map(strip).filter(Boolean);
  const want = strip(name);
  if (!lines.includes(want)) problems.push(`text not extracted (got: ${lines.slice(3, 6).join(" | ")})`);
  console.log(`${problems.length ? "✖" : "✔"} ${label.padEnd(9)} ${name}  ink=${ink}${problems.length ? `\n    ${problems.join("\n    ")}` : ""}`);
  if (problems.length) failed++;
}
console.log(`\n${Object.keys(NAMES).length - failed}/${Object.keys(NAMES).length} certificate PDFs render and extract correctly in Poppler (${out})`);
process.exit(failed ? 1 : 0);
