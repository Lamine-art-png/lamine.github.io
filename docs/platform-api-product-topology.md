# AGRO-AI Platform API Product Topology

This document defines the standalone developer product introduced by
`feat/api-platform-experience-v2`. It supplements `DEPLOYMENT_TRUTH_MAP.md` and
must be incorporated into that authoritative map before the pull request becomes
ready for review.

## Product surfaces

| Surface | Host or path | Runtime owner |
| --- | --- | --- |
| Platform marketing | `agroai-pilot.com/platform-api` | Marketing Cloudflare Pages project |
| Public developer docs | `agroai-pilot.com/platform-api/docs/` | Marketing Pages + guarded Pages Function |
| Enterprise Portal | `app.agroai-pilot.com` | Cloudflare Pages project `agroai-portal` |
| Controlled compatibility path | `app.agroai-pilot.com/platform/*` | Same authenticated Pages build |
| Standalone developer product | `platform.agroai-pilot.com` | Same authenticated Pages build, host-aware router |
| Machine API | `api.agroai-pilot.com/v1/platform/*` | Cloudflare Worker `agroai-api-edge` → FastAPI |
| Standalone same-origin API | `platform.agroai-pilot.com/v1/*` | Same production Worker route |

The standalone product reuses AGRO-AI authentication, verified organizations,
localization, session state, API client, backend models, and control-plane routes.
It does not introduce a second auth system or a second API backend.

## Authenticated product states

1. A signed-out visitor receives the existing secure AGRO-AI authentication flow,
   with Platform-specific product copy on the standalone hostname.
2. A verified but unenrolled organization receives the private-beta application
   experience.
3. A submitted application remains locked and exposes a review timeline only.
4. An approved active test enrollment exposes projects, service accounts, API
   keys, Playground, usage, request logs, webhooks, billing state, docs, support,
   settings, and controlled live-access state.
5. Live access is a separate reviewed request. It is never implied by test
   enrollment.
6. Physical irrigation execution remains disabled unless separately implemented,
   reviewed, configured, and activated.

Application submission creates a review record only. It cannot create projects,
issue keys, activate billing, accept draft legal documents, enable providers,
grant live access, or authorize physical actions.

## Browser security boundary

The authenticated Playground uses the Portal session and a server-mediated
endpoint. It operates only on organization-scoped deterministic test data.
Permanent Platform API keys do not enter browser JavaScript, `localStorage`, or
`sessionStorage`. Playground executions are audited, consume no production
credits, and cannot reach live providers or physical actions.

One-time key and webhook secrets may be displayed once after server-authorized
creation or rotation. They are not persisted by the Platform product.

## Cloudflare ownership

`wrangler.toml` owns these production API routes:

- `app.agroai-pilot.com/v1/*`
- `platform.agroai-pilot.com/v1/*`
- `api.agroai-pilot.com/v1/*`

The edge allowlist includes exact Portal, Platform, marketing, and approved Pages
origins. Lookalike origins remain denied. The Worker strips spoofable internal
forwarding headers and attaches authoritative client context only when the
matching edge-to-origin secret is configured.

The Pages custom domain must be attached and reviewed in Cloudflare before the
standalone hostname is advertised. Repository readiness does not prove that the
custom domain is already active.

## Private-beta activation truth

The initial private-beta configuration may enable:

- `PLATFORM_API_ENABLED`
- `PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED`
- `PLATFORM_API_TEST_PROJECTS_ENABLED`
- `PLATFORM_API_APPLICATIONS_ENABLED`
- `PLATFORM_API_PRIVATE_BETA_ENABLED`
- `PLATFORM_API_PARTNER_PROGRAM_ENABLED`
- `PLATFORM_API_SUPPORT_ENABLED`
- `PLATFORM_API_MARKETING_ENABLED`
- `PLATFORM_API_PUBLIC_DOCS_ENABLED`

`PLATFORM_API_INDEXING_ENABLED` must remain false or unset during private beta.
HTML responses remain `noindex, nofollow` even when marketing or docs are
available to approved users and reviewers.

The following remain disabled until their separate gates are satisfied:

- self-service sandbox enrollment;
- live projects and live-access requests;
- Platform API billing and Stripe checkout/meter export;
- public pricing and SDK downloads;
- webhook delivery;
- terms enforcement;
- automatic live approval;
- EarthDaily and Valley adapters;
- Valley physical write capability.

EarthDaily and Valley remain `awaiting_partner_contract`. Their presence in
readiness or application forms is not a claim that either integration is live.

## Public documentation and indexing boundary

`functions/platform-api/[[path]].ts` serves an explicit static allowlist.
Marketing and public docs have separate server-side availability flags. Shared
CSS, JavaScript, and logo assets are available when either surface is enabled,
so a marketing-only preview cannot render as a broken page. Disabled or unknown
routes return a genuine 404 with `noindex`; they never collapse into the landing
page.

Search indexing is a third, independent gate:

- `PLATFORM_API_MARKETING_ENABLED` controls the landing page.
- `PLATFORM_API_PUBLIC_DOCS_ENABLED` controls docs, reference, changelog, and the
  curated OpenAPI contract.
- `PLATFORM_API_INDEXING_ENABLED` removes `X-Robots-Tag: noindex, nofollow` from
  allowed HTML only after a deliberate public-launch decision.

Enabling indexing alone never exposes a disabled or unknown route. Those routes
continue to return `404`, `Cache-Control: no-store`, and
`X-Robots-Tag: noindex, nofollow`.

The reference is generated from the curated `/v1/platform/*` OpenAPI contract.
It may document reviewed paths and key prefixes, but must not invent endpoints,
pricing, provider readiness, certifications, uptime, latency, or live access.

## Activation order

1. Prove exact-head backend, PostgreSQL, Redis, edge, Portal, localization,
   browser, OpenAPI, SDK, and secret-scan checks.
2. Attach and validate the `platform.agroai-pilot.com` Pages custom domain without
   advertising it.
3. Enable private-beta backend and developer-control-plane gates for selected
   organizations only.
4. Enable marketing and documentation availability as required for the selected
   cohort while keeping indexing disabled.
5. Run production smoke tests against the exact deployed SHA and verify rollback.
6. Enable `PLATFORM_API_INDEXING_ENABLED` only for the later reviewed public
   launch, after legal, commercial, support, and observability approval.

## Release requirements

Before the product can be activated externally, exact-head CI must prove:

- public documentation truthfulness and OpenAPI fidelity;
- production build and existing Portal preservation;
- localization inventory and browser locale behavior;
- organization-isolated application review;
- test-only, keyless Playground behavior;
- projects, service accounts, key lifecycle, usage, logs, webhooks, and billing
  state through the existing backend;
- exact origin policy and standalone hostname Worker route;
- private-versus-public indexing behavior;
- PostgreSQL migration and concurrency contracts;
- no recognizable production credentials in the repository.

Production release must then prove the exact backend SHA, schema, Queue, object
storage, rate limiter, vault, edge auth, Pages build, and smoke tests. A passing
branch preview is not production activation.
