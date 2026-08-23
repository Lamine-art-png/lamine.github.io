# Enterprise Portal performance remediation

## Objective

The Enterprise Portal must feel immediate during sign-in, navigation, and language switching. Performance is a release property, not a cosmetic follow-up.

## Findings from current main

1. Authentication bootstrap uses several browser requests: `/v1/auth/me`, organizations, workspaces, then Platform developer overview. The browser pays multiple network/edge/backend round trips before the first authenticated shell is ready.
2. A token state change can cause session refresh work to overlap with the login-triggered refresh unless the client deduplicates it.
3. The authenticated route bundle starts loading only after authentication completes, adding JavaScript download/parse time after the session bootstrap.
4. Dynamic localization can require live translation generation. The browser performs critical, core, then full hydration with bounded retries. The edge has durable catalog caching, but a cold locale/provider path can still reach generation and upstream fallback timeouts.
5. A language change is locally authoritative and preference persistence is best-effort. Provider failure must never revert the user's explicit language choice.

## Implemented on the performance branch

### Login/session bootstrap

- `GET /v1/auth/bootstrap` returns the current user, organizations, token-selected active organization, workspaces, entitlements, verification state, and platform-admin state in one authenticated response.
- Existing endpoints remain available for compatibility, but the Enterprise Portal first-paint path uses the aggregate bootstrap endpoint.
- Concurrent browser refreshes share one in-flight bootstrap promise instead of issuing duplicate session requests.
- Platform API developer overview is not part of the Enterprise Portal first-paint response. It hydrates after the Enterprise Portal shell is released. It remains blocking only on the standalone/compatibility Platform API surfaces where it is required to choose the correct product gate.
- The bootstrap response exposes `Server-Timing` and `X-AGROAI-Bootstrap-Ms` and is explicitly `no-store`.
- Authenticated route code begins loading as soon as a stored/new token exists, while server validation continues. Rendering remains gated by validated authenticated user state.
- The Portal preconnects to the production API origin during boot.

Target: warm p95 API bootstrap <= 400 ms and warm p99 <= 800 ms from the US West production region.

### Localization

- The existing exact-key and placeholder validation remains fail-closed.
- Production localization releases now request the exact critical Portal source catalog for every supported dynamic locale before the live locale matrix runs. This warms the Cloudflare edge cache using the same locale + source fingerprint used by the browser.
- A separate weekly workflow refreshes those critical edge catalogs during quiet release periods so the 30-day cache does not become cold.
- Portuguese (`pt`) is included in the mandatory dynamic-locale prewarm and production matrix and is the Brazilian-demo acceptance locale until a separate `pt-BR` UI locale is explicitly enabled.
- On language selection, any validated local/edge catalog remains immediately reusable while core/full literals continue hydrating in the background.
- The full-screen transition remains bounded and is released as soon as the critical navigation/settings shell is available.

Targets: cached critical language switch <= 150 ms p95 and cold edge critical switch <= 800 ms p95.

### Frontend loading

- Preconnect to the API origin on Portal boot.
- Preload the authenticated route bundle while the session is being validated.
- Route/page data should use skeletons and progressive rendering rather than a full-screen loader once the shell is usable.
- Avoid duplicate fetches for session/workspace state.

## Remaining release gates

A production release is blocked until exact-head validation proves:

- backend auth/bootstrap tests pass;
- Portal production build and type checks pass;
- localization contract tests pass;
- every supported dynamic locale passes the production critical-shell prewarm/matrix;
- Portuguese can switch its critical shell without getting stuck or reverting the explicit user choice;
- login journey p95 is <= 2.0 s on warm infrastructure in synthetic US West checks;
- production timing evidence can distinguish edge/network time from backend/database bootstrap time.

## Infrastructure decision rule

Do not buy infrastructure before measurements prove the bottleneck. Cloudflare Pages/Workers should already make static shell delivery fast. If production timing shows Render cold starts or CPU saturation dominate the remaining latency, move the API service to an always-on paid instance. If PostgreSQL connection acquisition dominates, tune the bounded production pool and use a managed pooler where justified. Add Redis only where measured caching/session/rate-limit workloads justify it.

Prefer code-path removal, request consolidation, edge caching, prewarmed catalogs, and connection reuse first. A small infrastructure upgrade is justified when it measurably improves p95/p99 latency. Do not assume a $2-$5 monthly spend can guarantee enterprise latency; choose the least expensive tier that actually meets the measured target.
