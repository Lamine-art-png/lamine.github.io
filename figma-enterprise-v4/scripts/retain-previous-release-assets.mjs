// Carry the currently deployed release's hashed assets into the next
// deployment so tabs still running release N can finish loading their lazy
// chunks after N+1 ships (Cloudflare Pages serves only the latest
// deployment's files). Only the previous release's own asset graph is copied,
// so exactly one prior generation is retained. Hashed filenames never collide
// with the new build; existing files are never overwritten. Best effort: any
// failure is logged and skipped, it never blocks a release.
//
//   node scripts/retain-previous-release-assets.mjs --url https://app.agroai-pilot.com --dist dist [--save-index prev-index.html]
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, list) => {
  if (value.startsWith("--")) pairs.push([value.slice(2), list[index + 1]]);
  return pairs;
}, []));
const base = String(args.url || "").replace(/\/$/, "");
const dist = args.dist;
if (!base || !dist) throw new Error("--url and --dist are required");
const MAX_FILES = 600;
const MAX_BYTES = 80 * 1024 * 1024;

async function get(path, attempts = 4) {
  let last;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fetch(`${base}${path}`, { cache: "no-store", headers: { "Cache-Control": "no-cache" } });
    } catch (error) {
      last = error;
      await new Promise((resolve) => setTimeout(resolve, 1000 * attempt));
    }
  }
  throw last;
}

function referencedAssets(text) {
  const found = new Set();
  for (const match of text.matchAll(/(?:\/|\.\/|["'`])(assets\/[A-Za-z0-9._\-/]+\.(?:js|css|woff2?|svg|png|jpe?g|webp|wasm|json))/g)) found.add(match[1]);
  for (const match of text.matchAll(/["'`]\.\/([A-Za-z0-9._-]+\.(?:js|css|woff2?|svg|png|wasm))["'`]/g)) found.add(`assets/${match[1]}`);
  return found;
}

let copied = 0;
let bytes = 0;
try {
  const indexResponse = await get("/");
  const html = await indexResponse.text();
  if (!indexResponse.ok || !/<html/i.test(html)) throw new Error(`previous shell unavailable (${indexResponse.status})`);
  if (args["save-index"]) writeFileSync(args["save-index"], html);
  const previousBuild = html.match(/<meta name="agroai-build" content="([^"]+)"/)?.[1] || "unknown";
  const queue = [...referencedAssets(html)];
  const seen = new Set(queue);
  while (queue.length && copied < MAX_FILES && bytes < MAX_BYTES) {
    const asset = queue.shift();
    const target = join(dist, asset);
    let body;
    try {
      const response = await get(`/${asset}`);
      const type = response.headers.get("content-type") || "";
      if (!response.ok || /text\/html/i.test(type)) {
        console.warn(`skip ${asset}: ${response.status} ${type}`);
        continue;
      }
      body = Buffer.from(await response.arrayBuffer());
    } catch (error) {
      console.warn(`skip ${asset}: ${error}`);
      continue;
    }
    if (/\.(?:js|css)$/.test(asset)) {
      for (const next of referencedAssets(body.toString("utf8"))) {
        if (!seen.has(next)) {
          seen.add(next);
          queue.push(next);
        }
      }
    }
    if (existsSync(target)) continue;
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, body);
    copied += 1;
    bytes += body.length;
  }
  console.log(`retained_previous_release=${previousBuild} files=${copied} bytes=${bytes}`);
} catch (error) {
  console.warn(`previous release assets not retained: ${error}`);
}
