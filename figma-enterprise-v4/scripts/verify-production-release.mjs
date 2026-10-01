// Prove that production serves exactly the expected portal release with the
// intended cache policy. A Pages upload being accepted is not a release.
//
//   node scripts/verify-production-release.mjs --url https://app.agroai-pilot.com --sha <git sha> [--timeout-seconds 900]
//
// Transient network failures (connection resets while the edge converges) are
// retried with backoff; wrong content is never retried into success except
// while waiting for the deployment identity to converge.
const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, list) => {
  if (value.startsWith("--")) pairs.push([value.slice(2), list[index + 1]]);
  return pairs;
}, []));
const base = String(args.url || "").replace(/\/$/, "");
const sha = String(args.sha || "");
const timeoutMs = Number(args["timeout-seconds"] || 900) * 1000;
if (!base || !/^[A-Za-z0-9._-]{7,80}$/.test(sha)) throw new Error("--url and --sha are required");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const failures = [];
const check = (ok, message) => {
  if (!ok) failures.push(message);
  console.log(`${ok ? "ok  " : "FAIL"} ${message}`);
};

async function get(path, init = {}) {
  let last;
  for (let attempt = 1; attempt <= 6; attempt += 1) {
    try {
      const response = await fetch(`${base}${path}`, { cache: "no-store", redirect: "manual", ...init });
      return { response, body: Buffer.from(await response.arrayBuffer()) };
    } catch (error) {
      last = error;
      await sleep(1500 * attempt);
    }
  }
  throw new Error(`network failure for ${path}: ${last}`);
}

// 1. Wait for the release identity to converge on the custom domain.
const started = Date.now();
let deployment = null;
while (Date.now() - started < timeoutMs) {
  try {
    const { response, body } = await get(`/deployment.json?verify=${Date.now()}`);
    if (response.ok && /json/i.test(response.headers.get("content-type") || "")) {
      const data = JSON.parse(body.toString("utf8"));
      if (data.build_sha === sha) {
        deployment = { data, headers: response.headers };
        break;
      }
      console.log(`waiting: production reports ${data.build_sha}`);
    } else {
      console.log(`waiting: deployment.json ${response.status} ${response.headers.get("content-type")}`);
    }
  } catch (error) {
    console.log(`waiting: ${error.message}`);
  }
  await sleep(10_000);
}
check(Boolean(deployment), `production /deployment.json reports build ${sha}`);
if (!deployment) {
  console.error(failures.join("\n"));
  process.exit(1);
}
check(/no-store/i.test(deployment.headers.get("cache-control") || ""), "deployment.json is no-store");
check(deployment.data.environment === "production", "deployment.json environment is production");

// 2-6 run until every check agrees or the time budget is spent: Cloudflare
// Pages propagates deployment.json, the shell, assets and sw.js independently,
// so a single early pass can observe a transient mix. A release is only
// verified when one complete pass sees exactly this release everywhere.
async function verifyPass() {
  // 2. The shell (root and a deep link) is this release and never long-cached.
  for (const path of ["/", "/team"]) {
    const { response, body } = await get(`${path}?verify=${Date.now()}`);
    const html = body.toString("utf8");
    const cache = response.headers.get("cache-control") || "";
    check(response.status === 200 && /text\/html/i.test(response.headers.get("content-type") || ""), `${path} returns the HTML shell`);
    check(html.includes(`<meta name="agroai-build" content="${sha}"`), `${path} shell carries build ${sha}`);
    check(/no-store|max-age=0/i.test(cache) && !/immutable/i.test(cache), `${path} shell is revalidated (${cache})`);
    if (path === "/") {
      const entry = html.match(/<script type="module"[^>]*src="([^"]+)"/)?.[1];
      check(entry === deployment.data.entry, `shell entry ${entry} matches deployment entry ${deployment.data.entry}`);
    }
  }

  // 3. Every asset of this release's graph exists, is JavaScript/CSS, immutable.
  const { body: shellBody } = await get(`/?verify_assets=${Date.now()}`);
  const queue = [...new Set([...shellBody.toString("utf8").matchAll(/\/(assets\/[A-Za-z0-9._\-/]+\.(?:js|css))/g)].map((m) => m[1]))];
  const seen = new Set(queue);
  let assetFailures = 0;
  while (queue.length) {
    const asset = queue.shift();
    const { response, body } = await get(`/${asset}`);
    const type = response.headers.get("content-type") || "";
    const ok = response.status === 200 && !/text\/html/i.test(type) && /immutable/i.test(response.headers.get("cache-control") || "");
    if (!ok) {
      assetFailures += 1;
      console.log(`FAIL asset ${asset}: ${response.status} ${type} ${response.headers.get("cache-control")}`);
    }
    if (asset.endsWith(".js")) {
      const text = body.toString("utf8");
      for (const match of text.matchAll(/["'`]\.\/([A-Za-z0-9._-]+\.(?:js|css))["'`]/g)) {
        const next = `assets/${match[1]}`;
        if (!seen.has(next)) { seen.add(next); queue.push(next); }
      }
      for (const match of text.matchAll(/["'`](assets\/[A-Za-z0-9._\-/]+\.(?:js|css))["'`]/g)) {
        if (!seen.has(match[1])) { seen.add(match[1]); queue.push(match[1]); }
      }
    }
  }
  check(assetFailures === 0 && seen.size > 10, `all ${seen.size} release assets load as immutable non-HTML`);

  // 4. Retired or missing assets are an honest uncached 404, never the shell.
  {
    const { response } = await get(`/assets/agroai-release-probe-${sha.slice(0, 12)}.js`);
    const type = response.headers.get("content-type") || "";
    check(response.status === 404 && !/text\/html/i.test(type) && /no-store/i.test(response.headers.get("cache-control") || ""), `missing asset is an uncached 404 (${response.status} ${type})`);
  }

  // 5. The service worker is this release and never cached.
  {
    const { response, body } = await get(`/sw.js?env=production&verify=${Date.now()}`);
    check(/no-store/i.test(response.headers.get("cache-control") || ""), "sw.js is no-store");
    check(body.toString("utf8").includes(`const BUILD_ID = "${sha}";`), `sw.js is release ${sha}`);
  }

  // 6. The API through the edge is healthy and not publicly cacheable.
  {
    const { response, body } = await get("/v1/health");
    const cache = response.headers.get("cache-control") || "";
    let status = "";
    try { status = JSON.parse(body.toString("utf8")).status; } catch { status = ""; }
    check(response.status === 200 && status === "ok", "API /v1/health is ok through the edge");
    check(!/public|immutable|s-maxage/i.test(cache), `API response is not publicly cacheable (${cache || "no cache-control"})`);
  }

}

for (let pass = 1; ; pass += 1) {
  failures.length = 0;
  await verifyPass();
  if (!failures.length) break;
  if (Date.now() - started > timeoutMs) break;
  console.log(`pass ${pass} saw ${failures.length} inconsistency(ies); waiting for propagation`);
  await sleep(15_000);
}

if (failures.length) {
  console.error(`\nRelease verification failed:\n- ${failures.join("\n- ")}`);
  process.exit(1);
}
console.log(`\nproduction_release_verified=${sha}`);
