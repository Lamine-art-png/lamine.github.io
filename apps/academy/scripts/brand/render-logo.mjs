// Renders the official AGRO-AI Academy logo (brand/agro-ai-academy-logo.svg)
// at 2× with a transparent background, for scripts/brand/build_assets.py.
//
//   node scripts/brand/render-logo.mjs <out.png>
//
// The source is an artboard with a white backdrop; the backdrop rectangles are
// removed so the lockup keeps its own alpha. Needs Playwright's Chromium.
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const out = process.argv[2];
if (!out) throw new Error("usage: render-logo.mjs <out.png>");

let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch {
  ({ chromium } = await import("/opt/node-tools/node_modules/playwright/index.mjs"));
}

const svg = readFileSync(join(root, "brand/agro-ai-academy-logo.svg"), "utf8").replace(/<rect [^>]*fill="#ffffff"[^>]*\/>/g, "");
const tmp = join(mkdtempSync(join(tmpdir(), "academy-logo-")), "logo.svg");
writeFileSync(tmp, svg);
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 })).newPage();
await page.goto(`file://${tmp}`);
await page.screenshot({ path: out, omitBackground: true });
await browser.close();
