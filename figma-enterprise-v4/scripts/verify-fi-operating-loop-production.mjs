import fs from "node:fs/promises";
import path from "node:path";

const BACKEND_ORIGIN = "https://api-preview.agroai-pilot.com";
const PUBLIC_ORIGIN = "https://app.agroai-pilot.com";
const EXPECTED_BACKEND_SHA = "0539a1ae7e0c92ecdb621219f7135e2419b1b263";
const PROOF_PATH = path.resolve("public/fi-operating-loop-production-proof.json");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 30_000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal, redirect: "follow" });
  } finally {
    clearTimeout(timer);
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetchWithTimeout(url, options);
  const body = await response.text();
  let value;
  try {
    value = JSON.parse(body);
  } catch {
    throw new Error(`${url} did not return JSON (HTTP ${response.status}): ${body.slice(0, 240)}`);
  }
  if (!response.ok) {
    throw new Error(`${url} returned HTTP ${response.status}: ${JSON.stringify(value).slice(0, 240)}`);
  }
  return { response, value };
}

async function waitForBackend() {
  let last = "no response";
  for (let attempt = 1; attempt <= 90; attempt += 1) {
    try {
      const { value } = await fetchJson(`${BACKEND_ORIGIN}/v1/health`);
      last = JSON.stringify(value);
      if (value?.status === "ok" && value?.build_sha === EXPECTED_BACKEND_SHA) return value;
    } catch (error) {
      last = error instanceof Error ? error.message : String(error);
    }
    if (attempt < 90) await sleep(10_000);
  }
  throw new Error(`Render did not reach expected backend ${EXPECTED_BACKEND_SHA}. Last result: ${last}`);
}

function assertIncludes(haystack, needle, label = needle) {
  if (!haystack.includes(needle)) throw new Error(`Production portal bundle is missing ${label}`);
}

function extractJavaScriptAssets(text) {
  const assets = new Set();
  const patterns = [
    /(?:https?:\/\/[^"'`\s]+)?\/(assets\/[A-Za-z0-9._/-]+\.js)/g,
    /["'`](\.\/[^"'`\s]+\.js)["'`]/g,
    /["'`](assets\/[A-Za-z0-9._/-]+\.js)["'`]/g,
  ];
  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(text)) !== null) {
      const raw = match[1].replace(/^\.\//, "assets/");
      assets.add(raw.startsWith("assets/") ? raw : `assets/${raw}`);
    }
  }
  return assets;
}

async function collectPortalBundle() {
  const indexResponse = await fetchWithTimeout(`${PUBLIC_ORIGIN}/`);
  const index = await indexResponse.text();
  if (!indexResponse.ok) throw new Error(`Portal root returned HTTP ${indexResponse.status}`);
  if (!/<title>AGRO-AI Enterprise Portal<\/title>/.test(index)) {
    throw new Error("Production portal root did not return the AGRO-AI Enterprise Portal document");
  }

  const queue = [...extractJavaScriptAssets(index)];
  const seen = new Set();
  const bodies = [];
  while (queue.length && seen.size < 500) {
    const asset = queue.shift();
    if (!asset || seen.has(asset)) continue;
    seen.add(asset);
    const response = await fetchWithTimeout(`${PUBLIC_ORIGIN}/${asset}`);
    if (!response.ok) throw new Error(`Portal asset ${asset} returned HTTP ${response.status}`);
    const body = await response.text();
    bodies.push(body);
    for (const nested of extractJavaScriptAssets(body)) {
      if (!seen.has(nested)) queue.push(nested);
    }
  }
  if (!bodies.length) throw new Error("No production portal JavaScript assets were discovered");
  return { index, bundle: bodies.join("\n"), assetCount: seen.size };
}

async function main() {
  const startedAt = new Date().toISOString();
  const health = await waitForBackend();

  const { value: openapi } = await fetchJson(`${BACKEND_ORIGIN}/openapi.json`);
  const paths = openapi?.paths || {};
  const requiredRoutes = [
    "/v1/field-intelligence/live-analysis",
    "/v1/field-intelligence/live-transcription",
    "/v1/field-intelligence/observations/{observation_id}/tasks",
  ];
  for (const route of requiredRoutes) {
    if (!paths[route]?.post) throw new Error(`Deployed OpenAPI is missing POST ${route}`);
  }

  const { value: edgeHealth } = await fetchJson(`${PUBLIC_ORIGIN}/v1/edge-health`);
  if (edgeHealth?.status !== "ok") throw new Error(`Cloudflare edge is not healthy: ${JSON.stringify(edgeHealth)}`);

  const taskResponse = await fetchWithTimeout(
    `${PUBLIC_ORIGIN}/v1/field-intelligence/observations/production-proof/tasks`,
    { method: "POST", headers: { "content-type": "application/json" }, body: "{}" },
  );
  if (![401, 403, 404, 422].includes(taskResponse.status)) {
    throw new Error(`Unauthenticated observation task request returned unexpected HTTP ${taskResponse.status}`);
  }

  const { bundle, assetCount } = await collectPortalBundle();
  const markers = [
    ["/v1/field-intelligence/live-analysis", "live visual-analysis client"],
    ["/v1/field-intelligence/live-transcription", "live multilingual transcription client"],
    ["human_review_required", "human-review contract"],
    ["One observation. One operating loop.", "coherent operating-loop UI"],
    ["Task created and linked", "visible task confirmation"],
    ["field_observation_id", "linked Ask observation context"],
    ["source_observation_id", "task observation provenance"],
    ["/tasks?task_id=", "task deep link"],
    ["The transcript, media analysis, evidence, uncertainty, AGRO-AI discussion, and task stay linked.", "end-to-end workflow explanation"],
  ];
  for (const [needle, label] of markers) assertIncludes(bundle, needle, label);

  const proof = {
    status: "verified",
    started_at: startedAt,
    verified_at: new Date().toISOString(),
    product_release: EXPECTED_BACKEND_SHA,
    backend: {
      origin: BACKEND_ORIGIN,
      status: health.status,
      build_sha: health.build_sha,
      required_routes: requiredRoutes,
    },
    edge: { origin: PUBLIC_ORIGIN, status: edgeHealth.status },
    security: { unauthenticated_observation_task_http_status: taskResponse.status },
    portal: {
      origin: PUBLIC_ORIGIN,
      javascript_assets_checked: assetCount,
      verified_contracts: markers.map(([, label]) => label),
    },
    operating_loop: ["Capture", "Understand", "Decide", "Act"],
  };

  await fs.mkdir(path.dirname(PROOF_PATH), { recursive: true });
  await fs.writeFile(PROOF_PATH, `${JSON.stringify(proof, null, 2)}\n`, "utf8");
  console.log("FIELD_INTELLIGENCE_PRODUCTION_PROOF_OK");
  console.log(JSON.stringify(proof, null, 2));
}

main().catch((error) => {
  console.error("FIELD_INTELLIGENCE_PRODUCTION_PROOF_FAILED");
  console.error(error instanceof Error ? error.stack : error);
  process.exit(1);
});
