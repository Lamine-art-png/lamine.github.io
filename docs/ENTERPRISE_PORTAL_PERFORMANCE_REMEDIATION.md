# Enterprise Portal performance remediation

## Objective

The Enterprise Portal must feel immediate during sign-in, navigation, and language switching. Performance is a release property, not a cosmetic follow-up.

## Findings from the current production architecture

1. Authentication bootstrap is serialized in `AuthProvider.refreshMe()`: `/v1/auth/me`, organizations, workspaces, then Platform developer overview are awaited in sequence. The organization/workspace requests are also started only after `/auth/me` completes. This makes login wall-clock time the sum of several network/backend latencies.
2. The authenticated route bundle was imported only after `isAuthenticated` became true, so JavaScript download/parse time was added after session bootstrap. The performance branch overlaps route loading with token validation.
3. Dynamic localization can require live translation generation. The browser performs critical, core, then full hydration with bounded retries. The edge has durable catalog caching, but a cold locale/provider path can still reach generation and upstream fallback timeouts.
4. A language change is locally authoritative and preference persistence is best-effort. Provider failure must never revert the user's explicit language choice.

## P0 remediation required before calling the portal enterprise-grade

### Login/session bootstrap

- Add one authenticated `/v1/app/bootstrap` response containing the current user, organizations, active organization, workspaces, entitlements, verification state, and Platform developer-access boolean needed to render the first shell.
- Keep existing endpoints for compatibility, but make the Portal use the aggregate bootstrap endpoint for first paint.
- Run independent backend reads concurrently inside the bootstrap service.
- Do not block Enterprise Portal first paint on Platform API developer overview. That state is not required for the Enterprise Portal shell and can hydrate after first paint.
- Add `Server-Timing` for auth/database/bootstrap phases and propagate a request ID.
- Target warm p95 API bootstrap <= 400 ms and warm p99 <= 800 ms from the US West production region.

### Localization

- Stop depending on model generation in the interactive language-switch critical path for supported production locales.
- Build and publish versioned, validated critical/core locale catalogs at release time or through an asynchronous catalog build job.
- Serve immutable locale catalogs from Cloudflare edge/cache using locale + source fingerprint.
- On language selection: apply any validated local/edge catalog immediately, persist the choice locally, then hydrate remaining literals in the background.
- Never blank or block the entire Portal while full literal hydration runs. A short transition is acceptable only until the translated navigation/settings shell is available.
- Keep exact-key and placeholder validation fail-closed.
- Add Portuguese (`pt-BR`) as a mandatory release smoke locale because it is used in customer demos.
- Target cached critical language switch <= 150 ms p95 and cold edge critical switch <= 800 ms p95.

### Frontend

- Preconnect to the API origin on Portal boot.
- Preload the authenticated route bundle as soon as a valid-looking stored/new token exists while server validation runs. Rendering remains gated by authenticated user state.
- Route/page data requests must use skeletons and progressive rendering rather than a full-screen loader when the shell is already usable.
- Avoid duplicate fetches caused by multiple page-level hooks requesting the same session/workspace state.

### Infrastructure

Do not buy infrastructure before measurements prove the bottleneck. Cloudflare Pages/Workers should already make static shell delivery fast. If traces show Render cold starts or CPU saturation, move the API service to an always-on paid instance before adding more application complexity. If PostgreSQL connection acquisition dominates, use a bounded production pool and a managed pooler. Add Redis only where measured caching/session/rate-limit workloads justify it.

## Release gates

A production release is blocked if any of these fail:

- login journey p95 exceeds 2.0 s on warm infrastructure in synthetic US West checks;
- any supported locale cannot switch its critical shell;
- `pt-BR` critical/core/full catalog smoke fails;
- a language switch can leave the selector stuck, revert the explicit locale, or keep a full-screen cover indefinitely;
- first authenticated shell requires a nonessential Platform developer request;
- production traces cannot attribute time across edge, backend, database, and localization provider/cache.

## Cost policy

Prefer code-path removal, concurrency, edge caching, precomputed catalogs, and connection reuse first. A small always-on backend upgrade is justified if it removes verified cold-start latency. Do not assume a $2-$5 monthly spend can guarantee enterprise latency; choose the cheapest tier that meets measured p95/p99 targets and reassess with traffic growth.
