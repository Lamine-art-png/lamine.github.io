// Field Intelligence launch portal contract.
//
// Enforces the safety properties of the PWA shell, MapLibre map fallback,
// authorized media, sync recovery, draft review, and staging behavior.
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
   && sw.includes("const CACHE_VERSION = `${CACHE_FAMILY}v1`"));
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

if (failures > 0) {
  console.error(`Field Intelligence launch portal contract FAILED (${failures})`);
  process.exit(1);
}
console.log("Field Intelligence launch portal contract passed");
