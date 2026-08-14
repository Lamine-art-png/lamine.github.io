# AGRO-AI Platform API Product Topology

This document defines the current standalone developer product and its two deliberate operating modes: the existing reviewed private-beta fallback and the counsel-gated public TEST self-service launch. `DEPLOYMENT_TRUTH_MAP.md` remains the authoritative cross-product deployment map.

## Product surfaces

| Surface | Host or path | Runtime owner |
| --- | --- | --- |
| Platform marketing | `agroai-pilot.com/platform-api` | Cloudflare Worker `agroai-platform-api-marketing` + static Platform assets |
| Public developer docs | `agroai-pilot.com/platform-api/docs/` | Same guarded marketing Worker |
| Public CLI installers | `agroai-pilot.com/platform-api/assets/install.sh` and `install.ps1` | Same guarded marketing Worker |
| Enterprise Portal | `app.agroai-pilot.com` | Cloudflare Pages project `agroai-portal` |
| Controlled compatibility path | `app.agroai-pilot.com/platform/*` | Same authenticated Pages build |
| Standalone developer product | `platform.agroai-pilot.com` | Same authenticated Pages build, host-aware router |
| Machine API | `api.agroai-pilot.com/v1/platform/*` | Cloudflare Worker `agroai-api-edge` → FastAPI |
| Standalone same-origin API | `platform.agroai-pilot.com/v1/*` | Same production API edge |

The standalone product reuses AGRO-AI authentication, verified organizations, session state, API client, backend models, and control-plane routes. It does not create a second account system or a second API backend.

## Public TEST self-service journey

When the production public-launch contract is active:

1. A signed-out visitor on `platform.agroai-pilot.com` receives Platform-specific sign-in and registration.
2. Registration uses the existing automated agricultural organization verification engine. It does not bypass identity or organization verification.
3. The user verifies the email through the existing single-use verification-token boundary.
4. A verified organization owner/admin signs in and receives the exact current `approved_effective` Platform legal catalog.
5. The user accepts the current required documents by exact type/version.
6. The server grants the existing `developer_self_service` entitlement automatically with TEST-only, server-assigned limits.
7. The Developer Console opens immediately. No salesperson or API-access reviewer is required for the eligible TEST path.
8. The user can create TEST projects, service accounts, scoped `agro_test_` keys, deterministic TEST resources, jobs, usage and logs.
9. The same account may use the terminal flow: `agroai login` → browser device approval → `agroai bootstrap` → TEST API key → data-plane calls.

Public TEST self-service never implies LIVE access.

## Private-beta fallback

Before public activation, or if public activation is rolled back, the same product preserves the reviewed private-beta application gate. A verified but unenrolled organization receives the application experience instead of automatic enrollment. Submitted applications remain locked pending review.

The frontend detects launch readiness through server-authoritative legal and entitlement boundaries. It does not read or control backend feature flags from browser input.

## TEST/LIVE safety boundary

Automatic self-service is TEST-only. Server-assigned self-service limits set `allowed_environments=["test"]` and `maximum_live_projects=0`.

Public TEST activation does not enable:

- LIVE projects;
- automatic LIVE approval;
- production provider credentials or provider writes;
- production webhook delivery;
- billing/Stripe activation;
- physical irrigation execution;
- access to another organization’s resources or real customer data.

LIVE access remains a separate reviewed, contractual and technical process. EarthDaily and Valley remain `awaiting_partner_contract` until their separate gates are satisfied. Physical irrigation commands remain disabled.

## Browser security boundary

The authenticated Playground uses the Portal session and a server-mediated endpoint. It operates only on organization-scoped deterministic TEST data. Permanent Platform API keys do not enter browser JavaScript, `localStorage`, or `sessionStorage`.

New API-key plaintext may be displayed once after server-authorized creation or rotation. The Platform product does not persist that plaintext.

CLI human authentication is also separate from machine API keys. `agroai login` uses a first-party short-lived device authorization. The approved CLI credential is organization-bound and revocable; `agroai logout` revokes it server-side. Data-plane commands continue to use scoped project API keys.

## Public CLI distribution

A developer does not have to wait for a package-registry release to use the official CLI.

macOS/Linux:

```bash
curl -fsSL https://agroai-pilot.com/platform-api/assets/install.sh | sh
```

Windows PowerShell:

```powershell
iwr https://agroai-pilot.com/platform-api/assets/install.ps1 -UseBasicParsing | iex
```

The installers fetch the official repository source archive and create an isolated Python environment without requiring root/administrator access. PyPI, npm and Homebrew remain optional additional distribution channels and must not be advertised until namespace ownership and release credentials are verified.

## Marketing and indexing state machine

`cloudflare/platform-api-marketing-worker` owns the Platform marketing/docs routes. Four non-secret Worker values control availability and launch presentation:

- `PLATFORM_API_MARKETING_ENABLED`
- `PLATFORM_API_PUBLIC_DOCS_ENABLED`
- `PLATFORM_API_INDEXING_ENABLED`
- `PLATFORM_API_PUBLIC_SELF_SERVICE_ENABLED`

The committed Wrangler configuration keeps indexing and public-self-service presentation `false` by default. Therefore an ordinary code merge cannot accidentally announce or index a launch.

The protected activation workflow switches the Worker to public TEST self-service only after the backend TEST launch and effective legal catalog are proven. It also persists the repository Actions variable `PLATFORM_API_PUBLIC_SELF_SERVICE_LAUNCHED=true`, which the normal production marketing deploy workflow uses on subsequent releases. The rollback workflow sets that variable back to `false`, restores private-beta copy and `noindex`, and disables new automatic enrollment/device acquisition without deleting existing projects or keys.

Unknown or disabled Platform routes always remain genuine `404` responses with `noindex`.

## Legal activation boundary

Public automatic enrollment is fail-closed on an exact counsel-approved legal catalog. Draft legal text is not approval.

The activation boundary requires:

- `platform-api/legal/approved-catalog.json` with `status: "counsel_approved"`;
- a reviewer, approval reference and approval timestamp;
- exact versioned legal HTML assets under `platform-api/assets/legal/`;
- SHA-256 digests matching those exact assets;
- matching production `approved_effective` Platform terms records.

`platform-api/legal/validate_approved_catalog.py` validates evidence but cannot manufacture it.

## Production activation order

The protected workflow performs the launch in this order:

1. Refuse non-`main` or stale-main activation.
2. Require Render, Platform-admin and Cloudflare production credentials from the protected GitHub environment.
3. Validate counsel-approved legal evidence and exact public-asset digests.
4. Enable terms enforcement while automatic enrollment and CLI device auth remain off.
5. Deploy the exact main SHA.
6. Publish and verify the counsel-approved `approved_effective` legal records.
7. Enable only the TEST developer control plane, TEST projects, sandbox, auto-enrollment, terms enforcement and CLI device auth.
8. Explicitly write LIVE/provider/physical/webhook/billing flags to `false`.
9. Deploy the same exact main SHA and verify the production health boundary.
10. Deploy public TEST marketing/indexing mode and verify the public installer and legal/runtime contract.
11. Persist the public-launch Actions variable for future normal deployments.
12. Store immutable activation evidence.

## Release requirements

PR and production CI must prove:

- real front-door registration and email verification;
- exact current-terms acceptance and automatic TEST enrollment;
- project/service-account/key lifecycle;
- TEST-only terminal bootstrap;
- organization and project isolation;
- BOLA/IDOR and secret-sink regressions;
- PostgreSQL/Redis concurrency behavior;
- CLI device authorization, multi-org binding, single-winner token exchange and logout revocation;
- public installer execution on Linux and Windows;
- Portal product build and browser route contract;
- private/public marketing state, indexing state and genuine 404 behavior;
- exact backend SHA, schema, rate limiter, vault, edge context and production safety states.

A passing branch preview is not production activation. Public TEST self-service is launched only after the protected activation workflow succeeds on the exact deployed main release.