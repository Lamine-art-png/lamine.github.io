# AGRO-AI Platform API Product Topology

This document defines the standalone developer product and its two deliberate operating modes: reviewed private-beta fallback and counsel-gated public TEST self-service. `DEPLOYMENT_TRUTH_MAP.md` remains the authoritative cross-product deployment map.

## Product surfaces

| Surface | Host or path | Runtime owner |
| --- | --- | --- |
| Platform marketing | `agroai-pilot.com/platform-api` | Cloudflare Worker `agroai-platform-api-marketing` + static Platform assets |
| Public developer docs | `agroai-pilot.com/platform-api/docs/` | Same guarded marketing Worker |
| Public CLI installers | `agroai-pilot.com/platform-api/assets/install.sh` and `install.ps1` | Same guarded marketing Worker |
| Enterprise Portal | `app.agroai-pilot.com` | Cloudflare Pages project `agroai-portal` |
| Compatibility product path | `app.agroai-pilot.com/platform/*` | Same authenticated Pages build |
| Standalone developer product | `platform.agroai-pilot.com` | Same authenticated Pages build, host-aware router |
| Machine API | `api.agroai-pilot.com/v1/platform/*` | Cloudflare Worker `agroai-api-edge` → FastAPI |
| Standalone same-origin API | `platform.agroai-pilot.com/v1/*` | Same production API edge |

The standalone product reuses AGRO-AI authentication, verified organizations, session state, API client, backend models and control-plane routes. It does not create a second authentication system or API backend.

## Public TEST self-service journey

When the protected production launch contract is active:

1. A signed-out visitor on `platform.agroai-pilot.com` receives Platform-specific sign-in and registration.
2. Registration uses the existing automated agricultural organization-verification engine.
3. The user verifies the email through the existing single-use token boundary.
4. A verified organization owner/admin signs in and receives the exact current `approved_effective` Platform legal catalog.
5. The user accepts the required documents by exact type/version.
6. The server grants the existing `developer_self_service` TEST entitlement automatically with server-assigned limits.
7. The Developer Console opens immediately. No salesperson or API-access reviewer is required for the eligible TEST path.
8. The user can create TEST projects, service accounts, scoped `agro_test_` keys, deterministic TEST resources, jobs, usage and logs.
9. The same account can use `agroai login` → browser approval → `agroai bootstrap` → TEST key → data-plane calls.

Public TEST self-service never implies LIVE access.

## Private-beta fallback

Before public activation, or after rollback, an unenrolled verified organization receives the reviewed private-beta application gate instead of automatic enrollment. Application submission creates a review record only and cannot create projects or keys, accept draft legal documents, activate billing, connect production providers, grant LIVE access, deliver production webhooks or authorize physical actions.

The browser does not control backend feature flags. The server legal/entitlement state remains authoritative.

## TEST/LIVE safety boundary

Automatic self-service is TEST-only. Server-assigned self-service limits use `allowed_environments=["test"]` and `maximum_live_projects=0`.

Public TEST activation does not enable:

- LIVE projects;
- automatic LIVE approval;
- production provider credentials or provider writes;
- production webhook delivery;
- billing/Stripe activation;
- physical irrigation execution;
- access to another organization's resources or real customer data.

LIVE access remains a separate reviewed contractual and technical path. EarthDaily and Valley remain `awaiting_partner_contract` until their separate gates are satisfied. Physical irrigation commands remain disabled.

## Browser and CLI security boundary

The authenticated Playground uses the Portal session and a server-mediated endpoint. It operates only on organization-scoped deterministic TEST data. Permanent Platform API keys do not enter browser JavaScript, `localStorage` or `sessionStorage`.

New API-key plaintext may be displayed once after authorized creation/rotation and is not persisted by the product.

`agroai login` uses a first-party short-lived browser/device authorization. The approved human CLI credential is organization-bound and server-revocable. `agroai logout` revokes it server-side. Data-plane commands use project API keys, never the human session.

## Public CLI distribution

macOS/Linux:

```bash
curl -fsSL https://agroai-pilot.com/platform-api/assets/install.sh | sh
```

Windows PowerShell:

```powershell
iwr https://agroai-pilot.com/platform-api/assets/install.ps1 -UseBasicParsing | iex
```

The installers fetch the official public repository source archive and create an isolated Python environment without root/administrator access. PyPI, npm and Homebrew remain optional additional distribution channels and must not be advertised until namespace ownership and publishing credentials are verified.

## Marketing and indexing state machine

`cloudflare/platform-api-marketing-worker` owns the Platform marketing/docs routes.

The committed Wrangler defaults keep `PLATFORM_API_PUBLIC_SELF_SERVICE_ENABLED=false` and `PLATFORM_API_INDEXING_ENABLED=false`, so an ordinary code merge cannot announce or index a public launch.

The protected activation workflow switches the Worker to public TEST self-service only after backend TEST activation and the effective legal catalog are proven. The normal Platform marketing deployment does **not** rely on a mutable repository launch flag. It re-derives the mode from production truth:

- the exact Render service environment must show Platform API, control plane, TEST projects, sandbox, TEST auto-enrollment, terms enforcement and CLI device auth enabled;
- `/v1/platform/health` must show CLI device auth enabled with production secret readiness and the normal runtime safety gates;
- `/v1/platform/terms` must expose the required effective legal documents.

If the runtime looks partially/publicly activated but Render environment read access is unavailable, the marketing deploy fails instead of guessing. If the self-service backend flags are off, the Worker is deployed in private-beta/noindex mode.

Rollback disables TEST auto-enrollment and CLI device acquisition in Render first, then restores private-beta/noindex marketing. Future normal marketing releases therefore continue to infer the private state automatically.

Unknown or disabled Platform routes always remain genuine HTTP 404 responses with `noindex`.

## Legal activation boundary

Public automatic enrollment is fail-closed on exact counsel-approved legal evidence. Draft legal text is not approval.

Activation requires:

- `platform-api/legal/approved-catalog.json` with `status: "counsel_approved"`;
- reviewer, approval reference and approval timestamp;
- exact versioned legal HTML assets under `platform-api/assets/legal/`;
- SHA-256 digests matching those exact assets;
- matching production `approved_effective` Platform terms records.

`platform-api/legal/validate_approved_catalog.py` validates evidence but cannot manufacture it.

## Production activation order

The protected workflow performs the launch in this order:

1. refuse non-`main` or stale-main activation;
2. require Render, Platform-admin and Cloudflare credentials from the protected production environment;
3. validate counsel-approved legal evidence and exact asset digests;
4. enable terms enforcement while automatic enrollment and CLI device auth remain off;
5. deploy exact main SHA;
6. publish and verify counsel-approved `approved_effective` records;
7. enable only TEST control plane, TEST projects, sandbox, auto-enrollment, terms enforcement and CLI device auth;
8. explicitly set LIVE/provider/physical/webhook/billing flags false;
9. deploy the same exact main SHA and verify Platform runtime safety;
10. verify public legal assets by exact digest;
11. deploy public TEST marketing/indexing mode and verify installer/public state;
12. upload immutable activation evidence.

## Release requirements

PR and production CI must prove:

- real front-door registration and email verification;
- current-terms acceptance and automatic TEST enrollment;
- project/service-account/key lifecycle;
- TEST-only terminal bootstrap;
- organization/project isolation and BOLA/IDOR controls;
- secret-sink regressions;
- PostgreSQL/Redis concurrency behavior;
- CLI device authorization, multi-org binding, single-winner exchange and logout revocation;
- public installer execution on Linux and Windows;
- Portal product build and browser route contract;
- private/public marketing state, indexing and genuine 404 behavior;
- exact backend SHA, schema, rate limiter, vault, edge context and production safety states.

A passing branch preview is not production activation. Public TEST self-service is live only after the protected activation workflow succeeds on the exact production release.