# Portal release convergence

Invariant: every customer runs the current AGRO-AI Enterprise Portal release
without having to know about caches, service workers, deployments or versions,
and converging never costs them their session, language, workspace or unsaved
work.

## Incident (2026-09-30) and root causes

A customer onboarding live ran a different portal from ours: no language
selector, "Backend unavailable" while the backend was healthy, and different
authentication behaviour.

1. **Three production deployers raced for the same Pages project.** Every
   frontend push to `main` ran `deploy.yml`, `deploy-portal-language.yml` and
   `assurance-portal-visibility-release.yml`, each building its own bundle and
   running `wrangler pages deploy` to `agroai-portal` in separate concurrency
   groups. Whichever finished last became production:
   - `assurance-portal-visibility-release.yml` built with
     `VITE_API_BASE_URL=https://api.agroai-pilot.com`, the DNS-only host that
     bypasses the Cloudflare edge. Its bundle made cross-origin API calls
     that fail in the browser ("Backend unavailable. Retry." is the client's
     message for a thrown fetch) and behave differently on auth.
   - `deploy-portal-language.yml` built without `VITE_DEPLOYMENT_ENVIRONMENT`
     or `VITE_BUILD_SHA`: no service worker registration, no build identity.
   Each deployment also retired the others' hashed chunks.
2. **Missing assets were served as HTML, cached for a year.** A request for an
   `/assets/*` file not in the live deployment fell through to the SPA shell
   (`200 text/html`) and inherited `Cache-Control: public, max-age=31536000,
   immutable`, permanently poisoning that chunk URL in the browser.
3. **Freshness was only checked at boot** (and unbounded), so an open tab ran
   an old release indefinitely; a retired lazy route showed "This workspace
   module is not available yet."
4. **No release identity or telemetry**: nothing showed which build a browser
   ran or how much traffic came from stale builds.

## Architecture

| Layer | Policy |
| --- | --- |
| `/`, `/index.html` | `no-store` |
| SPA deep links (`/team`, …) | `max-age=0, must-revalidate` (Pages default for the shell) |
| `/sw.js`, `/deployment.json` | `no-store` |
| `/assets/*` present | `public, max-age=31536000, immutable` |
| `/assets/*` missing | `functions/assets/[[path]].ts` → `404`, `no-store`, never HTML |
| `/manifest.webmanifest` | `no-cache, must-revalidate` |
| `/v1/*` | never intercepted or cached by the service worker |

- **One deployer.** Only `deploy.yml` deploys the portal (same-origin API,
  production service worker, `VITE_BUILD_SHA=${github.sha}`). The language and
  Assurance workflows validate and then verify production after
  `.github/scripts/wait-for-portal-release.sh` sees their commit live (or a
  newer one). The Cloudflare Pages topology contract fails CI if any other
  workflow deploys the portal.
- **Identity.** `vite.config.ts` compiles the Git SHA into the bundle, emits
  `/deployment.json` (`build_sha`, `entry`, `built_at`, `environment`), adds
  `<meta name="agroai-build">`, and stamps the SHA into `sw.js`.
- **Service worker.** One cache per release (`agroai-shell-<env>-<sha>`); a new
  release is a byte-different worker that installs, `skipWaiting`s, claims and
  deletes the previous release's cache. Navigation is network-first (offline
  fallback only); JavaScript requests never receive HTML.
- **Asset retention.** Before uploading release N+1, `deploy.yml` copies
  release N's asset graph into the new deployment
  (`scripts/retain-previous-release-assets.mjs`), so tabs still on N keep
  loading their lazy chunks until they converge. One generation is retained.
- **Convergence runtime** (`src/release/releaseRuntime.ts`):
  - detects a different production release at boot (≤ 2.5 s, fail-open),
    on return to the tab, focus, reconnect, bfcache restore, service-worker
    takeover, and every 15 min while visible (throttled to ≥ 60 s);
  - converges only at safe points: route navigation, tab hidden, return to
    the tab, or ≥ 10 min idle;
  - never while an input has unsaved text, a write request/upload is in
    flight, microphone/camera capture is live, a single-use link page
    (`/verify-email`, `/accept-invite`, `/recover-account`,
    `/reset-password`) is open, or code holds `holdRelease()`;
  - applying is a plain reload: storage (token, locale, workspace) is never
    cleared;
  - tabs share discoveries via `BroadcastChannel` (storage-event fallback),
    each converging at its own safe point;
  - a retired lazy chunk or stale boot asset loads the current release;
  - loop guard: two immediate attempts per target, then exponential backoff
    (2, 4, 8… min) with `reload_loop_prevented` reported.
- **Compatibility.** The portal only calls the API same-origin through the
  edge. Backwards compatibility of request schemas across one release remains
  a code-review responsibility; the `X-AGROAI-Client-Build` header makes skew
  visible.

## Release gates (`deploy.yml`)

Validate (i18n contracts, build) → deploy edge → wait for the exact backend
SHA → build → retain previous assets → deploy Pages →
`scripts/verify-production-release.mjs` (custom domain serves this SHA in
`deployment.json`, shell meta and entry; every release asset is immutable
non-HTML; missing asset is an uncached 404; `sw.js` is this release and
`no-store`; `/v1/health` ok and not publicly cacheable) → language bundle
smoke → `tests/browser/production-release.spec.mjs` in a real browser (fresh
client runs this SHA with only this release's SW cache and no `/v1` entries; a
client served the previous release's shell converges to this SHA with its
language intact).

## Rollback

Redeploy a previous commit through `deploy.yml` (`workflow_dispatch` on that
ref) or promote an earlier Pages deployment. Releases are compared by
equality, so browsers on the bad release see a different `build_sha` and
converge back exactly as they converge forward; the service worker cache is
per release, never "newest wins". Promoting a Pages deployment from before
release identity existed is handled by the runtime's shell probe (entry
module comparison).

## Observability

- `POST /v1/client/release-events` logs `frontend_release_event` lines:
  `stale_build_detected`, `recovery_attempted`, `recovery_succeeded`,
  `recovery_deferred`, `reload_loop_prevented`, `asset_load_failure`,
  `dynamic_import_failure`, `service_worker_updated`, with running/latest
  build, route family (first path segment), trigger/reason category and
  visibility only.
- API requests carry `X-AGROAI-Client-Build` (same-origin only); the API logs
  a sampled `frontend_build_skew` line when it differs from the deployed
  backend SHA.

## Tests

- `tests/browser/release-convergence.spec.mjs` (PR CI, real Chromium, two real
  builds behind `tests/release-harness/server.mjs`): fresh client, returning
  client with old SW/cache, active tab (session + Portuguese survive), unsaved
  input deferred to navigation, two tabs without reload storm, retired lazy
  chunk, rollback, offline → online, partial propagation without reload loop,
  restricted storage.
- `tests/browser/production-release.spec.mjs` (post-deploy, production).
- `tests/frontend-runtime-recovery-contract.mjs`, backend
  `tests/unit/test_client_release_events.py`.

## Known limits

- A tab whose page keeps unsaved input and never navigates stays on its
  release until the customer navigates or the input is left; this is
  deliberate (never discard work).
- Only one previous release's assets are retained; a tab two or more
  releases old that lazy-loads a retired chunk reloads into the current
  release instead.
