// Field Intelligence launch portal contract.
//
// Enforces the safety properties of the PWA shell, MapLibre map fallback,
// authorized media, sync recovery, draft review, staging behavior, and the
// current public launch surfaces.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
let failures = 0;
function ok(name, condition, detail = "") {
  if (condition) console.log(`  ok - ${name}`);
  else {
    failures += 1;
    console.error(`  FAIL - ${name}${detail ? ` — ${detail}` : ""}`);
  }
}

// --- Service worker: static shell only, never authenticated data -----------
const sw = readFileSync(join(root, "public", "sw.js"), "utf8");
ok("sw exists and has an environment-scoped version family",
   sw.includes("const CACHE_FAMILY = `agroai-shell-${SW_ENV}-`")
   && /const CACHE_VERSION = `\$\{CACHE_FAMILY\}v\d+`;/.test(sw));
ok("sw never touches non-GET requests", sw.includes('request.method !== "GET"'));
ok("sw never touches cross-origin requests", sw.includes("url.origin !== self.location.origin"));
ok("sw never caches API paths", sw.includes('url.pathname.startsWith("/v1/")'));
ok("sw deletes only stale caches from its own environment",
   sw.includes("name.startsWith(CACHE_FAMILY) && name !== CACHE_VERSION")
   && !sw.includes("names.filter((name) => name !== CACHE_VERSION)"));
ok("sw supports user-consented updates", sw.includes("SKIP_WAITING"));
ok("sw caches no Authorization-bearing route", !/authorization/i.test(sw));

// --- Manifest ---------------------------------------------------------------
const manifest = JSON.parse(readFileSync(join(root, "public", "manifest.webmanifest"), "utf8"));
ok("manifest is installable", manifest.display === "standalone" && manifest.start_url === "/");
ok("manifest has icons", Array.isArray(manifest.icons) && manifest.icons.length > 0);
ok("index.html links the manifest",
   readFileSync(join(root, "index.html"), "utf8").includes('rel="manifest"'));

// --- SW registration: declared production/staging only ---------------------
const main = readFileSync(join(root, "src", "main.tsx"), "utf8");
ok("sw registered only for declared deployment environments",
   main.includes("VITE_DEPLOYMENT_ENVIRONMENT")
   && main.includes('["production", "staging"].includes(deploymentEnvironment)')
   && main.includes("!import.meta.env.DEV"));
ok("sw update dispatches user-visible event", main.includes("agroai:sw-update"));
ok("staging and production caches cannot collide",
   sw.includes('searchParams.get("env")') && main.includes("/sw.js?env=")
   && sw.includes("CACHE_FAMILY"));

// --- MapLibre map -----------------------------------------------------------
const map = readFileSync(join(root, "src", "app", "fieldIntelligence", "FieldMap.tsx"), "utf8");
ok("map style comes from the backend, not a bundled secret",
   map.includes("apiClient.fieldIntelligence.map(") && !/api[_-]?key|token\s*[:=]\s*["']/i.test(map));
ok("map clusters observations", map.includes("cluster: true"));
ok("map has severity encoding", map.includes("SEVERITY_COLORS"));
ok("map degrades to accessible fallback", map.includes("fieldIntel.mapFallback"));
ok("map is lazy-loaded", map.includes('await import("maplibre-gl")'));

// --- Media viewer -----------------------------------------------------------
const media = readFileSync(join(root, "src", "app", "fieldIntelligence", "MediaViewer.tsx"), "utf8");
ok("media bytes fetched through the authorized client", media.includes("apiClient.fieldIntelligence.assetBlob"));
ok("media object URLs are revoked", media.includes("URL.revokeObjectURL"));
ok("media handles deleted state", media.includes("fieldIntel.mediaDeleted"));
ok("no permanent public object URL is built", !media.includes("s3://") && !/https?:\/\/[^"']*amazonaws/.test(media));

// --- Composer: recorder lifecycle + draft review ----------------------------
const fi = readFileSync(join(root, "src", "app", "components", "FieldIntelligence.tsx"), "utf8");
ok("recorder enforces a maximum duration", fi.includes("MAX_RECORDING_SECONDS"));
ok("stop/save race is awaited before review", fi.includes("await stopRecording()"));
ok("microphone stream is released on unmount", fi.includes("releaseStream"));
ok("draft review exists before submission", fi.includes("fieldIntel.reviewTitle") && fi.includes("fieldIntel.confirmQueue"));
ok("attachments can be removed pre-submit", fi.includes("removeAttachment"));
ok("retake is offered", fi.includes("fieldIntel.retake"));

// --- Sync center ------------------------------------------------------------
const syncCenter = readFileSync(join(root, "src", "app", "fieldIntelligence", "SyncCenter.tsx"), "utf8");
ok("sync center namespaces the queue per identity", syncCenter.includes("configureIdentity"));
ok("sync center offers retry/inspect/export/discard",
   ["syncCenter.retry", "syncCenter.inspect", "syncCenter.export", "syncCenter.discard"]
     .every((key) => syncCenter.includes(key)));
ok("discard requires confirmation", syncCenter.includes("syncCenter.discardConfirm"));
const layout = readFileSync(join(root, "src", "app", "components", "MainLayout.tsx"), "utf8");
ok("sync center is mounted in the portal shell", layout.includes("<SyncCenter />"));

const summarizeSource = syncCenter
  .slice(syncCenter.indexOf("export function summarizeQueue"), syncCenter.indexOf("export function SyncCenter"))
  .replace("export function summarizeQueue(records: CaptureRecord[]): SyncSummary {", "function summarizeQueue(records) {")
  .replace(/const count = \(state: SyncState\)/, "const count = (state)");
// eslint-disable-next-line no-new-func
const summarize = new Function(`${summarizeSource}; return summarizeQueue;`)();
const summary = summarize([
  { syncState: "queued" }, { syncState: "draft" }, { syncState: "syncing" },
  { syncState: "failed" }, { syncState: "conflict" }, { syncState: "manual_recovery" },
  { syncState: "synced" },
]);
ok("summarize counts queued+draft together", summary.queued === 2);
ok("summarize flags attention states", summary.attention === 3);
ok("summarize totals all records", summary.total === 7);

// --- Staging experience -----------------------------------------------------
const banner = readFileSync(join(root, "src", "app", "components", "StagingBanner.tsx"), "utf8");
ok("staging banner is build-variable gated", banner.includes('DEPLOYMENT_ENVIRONMENT === "staging"'));
ok("staging banner never renders undeclared", banner.includes("if (!isStagingBuild()) return null"));
ok("staging banner shows the exact build SHA", banner.includes("VITE_BUILD_SHA") && banner.includes(".slice(0, 10)"));
ok("staging pages are noindexed", banner.includes('"noindex, nofollow"'));
ok("staging banner is mounted in the shell", layout.includes("<StagingBanner />"));
ok("staging banner exposes no secrets or origins", !/https?:\/\//.test(banner));

// --- Live newsroom and announcement verification ---------------------------
const liveUrls = {
  newsroom: "https://agroai-pilot.com/news",
  restoreScript: "https://agroai-pilot.com/news/agroai-news-card-restore.js",
  deere: "https://agroai-pilot.com/news/agro-ai-connected-john-deere-operations-center",
  deereCover: "https://agroai-pilot.com/news/agro-ai-connected-john-deere-operations-center/cover.webp",
  field: "https://agroai-pilot.com/news/introducing-agro-ai-field-intelligence",
  fieldCover: "https://agroai-pilot.com/news/introducing-agro-ai-field-intelligence/cover.webp",
};

async function fetchLive(url, attempts = 24) {
  let lastResponse = null;
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const target = new URL(url);
      target.searchParams.set("verify", `${Date.now()}-${attempt}`);
      lastResponse = await fetch(target, {
        redirect: "follow",
        headers: { "cache-control": "no-cache", "user-agent": "AGRO-AI-Live-News-Contract/1.0" },
      });
      if (lastResponse.ok) return lastResponse;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 5000));
  }
  if (lastError && !lastResponse) throw lastError;
  return lastResponse;
}

try {
  const newsroomResponse = await fetchLive(liveUrls.newsroom);
  const newsroomHtml = newsroomResponse ? await newsroomResponse.text() : "";
  ok("live newsroom returns native HTML", Boolean(newsroomResponse?.ok && /<!doctype html|<html/i.test(newsroomHtml)), `status=${newsroomResponse?.status ?? "network-error"}`);
  ok("live newsroom comes from the native Pages origin", newsroomResponse?.headers.get("x-agroai-newsroom-source") === "native-pages-origin", newsroomResponse?.headers.get("x-agroai-newsroom-source") || "missing header");
  ok("live newsroom loads only the restoration script", newsroomHtml.includes("/news/agroai-news-card-restore.js") && !newsroomHtml.includes("field-intelligence-newsroom.css"));

  const scriptResponse = await fetchLive(liveUrls.restoreScript);
  const script = scriptResponse ? await scriptResponse.text() : "";
  ok("newsroom restoration script is live", Boolean(scriptResponse?.ok), `status=${scriptResponse?.status ?? "network-error"}`);
  ok("restoration script restores Field Intelligence card", script.includes("Introducing AGRO-AI Field Intelligence") && script.includes("/news/introducing-agro-ai-field-intelligence"));
  ok("restoration script publishes John Deere card", script.includes("AGRO-AI connects with John Deere Operations Center™") && script.includes("/news/agro-ai-connected-john-deere-operations-center"));
  ok("restoration script does not inject CSS", !/createElement\(["']style["']\)|\.style\.|insertRule|stylesheet/i.test(script));

  const deereResponse = await fetchLive(liveUrls.deere);
  const deereHtml = deereResponse ? await deereResponse.text() : "";
  ok("reviewed John Deere article is publicly live", Boolean(deereResponse?.ok), `status=${deereResponse?.status ?? "network-error"}`);
  ok("John Deere article contains reviewed website copy",
     deereHtml.includes("AGRO-AI connects with John Deere Operations Center™")
     && deereHtml.includes("Agricultural operations do not suffer from a shortage of data.")
     && deereHtml.includes("Access is initiated through the user's Operations Center connection."));
  ok("John Deere article retains author and publication metadata",
     deereHtml.includes('<meta name="author" content="AGRO-AI"')
     && deereHtml.includes("Tuesday, July 28, 2026 at 8:00 AM PDT")
     && deereHtml.includes("San Francisco, California"));
  ok("John Deere article retains customer and social links",
     [
       "https://app.agroai-pilot.com/integrations",
       "https://agroai-pilot.com/enterprise-portal",
       "https://agroai-pilot.com/book-a-demo",
       "https://agroai-pilot.com/platform-api/",
       "https://www.linkedin.com/company/agro-ai-inc/",
       "https://www.instagram.com/agroai.inc/",
       "https://www.youtube.com/channel/UCd3tQLAOtMmjFhRNVdU08tA",
     ].every((link) => deereHtml.includes(link)));

  const deereCoverResponse = await fetchLive(liveUrls.deereCover);
  const deereCoverBytes = deereCoverResponse ? (await deereCoverResponse.arrayBuffer()).byteLength : 0;
  ok("supplied John Deere cover is publicly live",
     Boolean(deereCoverResponse?.ok
       && (deereCoverResponse.headers.get("content-type") || "").includes("image/webp")
       && deereCoverResponse.headers.get("x-agroai-asset-source") === "reviewed-john-deere-cover"
       && deereCoverBytes > 10000),
     `status=${deereCoverResponse?.status ?? "network-error"}, bytes=${deereCoverBytes}`);

  const fieldResponse = await fetchLive(liveUrls.field);
  const fieldHtml = fieldResponse ? await fieldResponse.text() : "";
  ok("Field Intelligence announcement article remains publicly live", Boolean(fieldResponse?.ok), `status=${fieldResponse?.status ?? "network-error"}`);
  ok("Field Intelligence announcement retains its launch content", fieldHtml.includes("Introducing AGRO-AI Field Intelligence") && fieldHtml.includes("GiM6WZY0HG0"));

  const fieldCoverResponse = await fetchLive(liveUrls.fieldCover);
  ok("Field Intelligence cover remains publicly live",
     Boolean(fieldCoverResponse?.ok && fieldCoverResponse.headers.get("x-agroai-cover-target") === "3840x2160"),
     `status=${fieldCoverResponse?.status ?? "network-error"}`);
} catch (error) {
  ok("live newsroom verification completed", false, error instanceof Error ? error.message : String(error));
}

if (failures > 0) {
  console.error(`Field Intelligence launch portal contract FAILED (${failures})`);
  process.exit(1);
}
console.log("Field Intelligence launch portal contract passed");
