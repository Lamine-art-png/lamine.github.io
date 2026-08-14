# AGRO-AI Deployment Truth Map

This document is the authoritative release topology for the current AGRO-AI platform. It records runtime ownership, deployment boundaries, launch state, and safety gates. It must be updated whenever routing, runtime ownership, or an externally visible activation contract changes.

## A. Marketing website and Platform API public surface

Primary marketing host:

`agroai-pilot.com`

The main marketing application is deployed on Cloudflare Pages. The Platform API public surface is deliberately narrower and is owned by the Cloudflare Worker `agroai-platform-api-marketing` for the exact routes under `/platform-api` plus the product-entry route at `/`.

Platform API public surfaces:

- landing page: `https://agroai-pilot.com/platform-api`
- docs: `https://agroai-pilot.com/platform-api/docs/`
- reference: `https://agroai-pilot.com/platform-api/reference.html`
- changelog: `https://agroai-pilot.com/platform-api/changelog.html`
- public CLI installers: `/platform-api/assets/install.sh` and `/platform-api/assets/install.ps1`
- versioned legal assets after counsel approval: `/platform-api/assets/legal/*`

Authoritative Worker source:

- `cloudflare/platform-api-marketing-worker/src/index.ts`
- `cloudflare/platform-api-marketing-worker/wrangler.toml`

The Worker uses four explicit, non-secret product-state values:

- `PLATFORM_API_MARKETING_ENABLED`
- `PLATFORM_API_PUBLIC_DOCS_ENABLED`
- `PLATFORM_API_INDEXING_ENABLED`
- `PLATFORM_API_PUBLIC_SELF_SERVICE_ENABLED`

The committed Wrangler defaults keep public self-service presentation and search indexing disabled. A normal code merge therefore cannot accidentally announce a public launch. Unknown or disabled routes return a genuine HTTP 404 with `noindex` rather than falling through to a generic marketing SPA.

During reviewed private beta, the Worker serves private-beta product copy and `X-Robots-Tag: noindex, nofollow`.

After the protected public TEST activation succeeds, the Worker serves self-service TEST copy, removes the private-beta `noindex` header from allowed HTML, exposes the public installers, and records `x-agroai-platform-api-access: public-test-self-service`. LIVE, provider, webhook and physical capabilities are unaffected by this marketing state.

## B. Enterprise Portal

Primary host:

`app.agroai-pilot.com`

Runtime: Cloudflare Pages project `agroai-portal`.

Authoritative application source:

`figma-enterprise-v4/`

Production builds use:

`VITE_API_BASE_URL=https://api.agroai-pilot.com`

The browser uses the custom API domain and never receives the private upstream application origin.

The Enterprise Portal remains the agricultural operating surface for operations, Field Intelligence, evidence, recommendations, reports, integrations, billing, account security and internal administration.

## B2. Standalone Platform API developer product

Primary host:

`platform.agroai-pilot.com`

Compatibility path:

`app.agroai-pilot.com/platform/*`

Runtime: the same reviewed Cloudflare Pages build as the Enterprise Portal, selected by an exact host-aware router.

Key source files:

- `figma-enterprise-v4/src/app/components/PlatformAuthScreen.tsx`
- `figma-enterprise-v4/src/app/components/PlatformSelfServiceGate.tsx`
- `figma-enterprise-v4/src/app/components/PlatformCliDeviceApproval.tsx`
- `figma-enterprise-v4/src/app/components/PlatformApplicationGate.tsx`
- `figma-enterprise-v4/src/app/components/PlatformConsole.tsx`
- `figma-enterprise-v4/src/app/components/PlatformSafetyNotice.tsx`
- `figma-enterprise-v4/src/app/routes.tsx`

The standalone product reuses the existing AGRO-AI account system, automated organization verification, sessions, localization, API client, backend models and Platform control-plane routes. It does not create a second authentication system or a second Platform backend.

### Public TEST self-service state

When the protected public-launch contract is active:

1. a signed-out visitor receives Platform-specific registration and sign-in;
2. registration goes through the existing agricultural organization-verification engine;
3. the user confirms a single-use email verification token;
4. a verified owner/admin signs in;
5. the product loads the current effective Platform legal catalog from the backend;
6. the owner/admin accepts each required document by exact type/version;
7. the server grants the existing `developer_self_service` TEST-only entitlement automatically;
8. the Developer Console becomes available without a salesperson or API-access reviewer;
9. the developer can create TEST projects, service accounts, scoped `agro_test_` keys, deterministic test resources, jobs, usage and request logs.

Automatic enrollment is server-authoritative. The browser cannot choose its own environment, quota, program, organization, or privilege level.

### Private-beta fallback

Before public activation, or after a public rollback, an unenrolled verified organization receives the reviewed private-beta application gate instead. Application submission creates a review record only. It cannot create a project or key, accept draft legal text, activate billing, connect a production provider, grant LIVE access, deliver a production webhook, or authorize a physical action.

### CLI browser approval

`/cli` is the first-party browser approval screen used by `agroai login`. Device authorization is short-lived, organization-bound, single-exchange and server-revocable. The browser never asks for a machine API key. `agroai logout` revokes the human CLI session server-side.

## C. API edge

Machine API:

`api.agroai-pilot.com/v1/*`

Same-origin authenticated product routes:

- `app.agroai-pilot.com/v1/*`
- `platform.agroai-pilot.com/v1/*`

Runtime: Cloudflare Worker `agroai-api-edge`.

Authoritative source:

- `cloudflare/edge-gateway/src/index.ts`
- `cloudflare/edge-gateway/src/edge-main-v3.ts`
- root `wrangler.toml`

Responsibilities include exact browser-origin policy, bounded request IDs, security response headers, removal of spoofable forwarding headers, fail-closed upstream configuration, recursion protection, trusted edge-to-origin client context, bounded retry for safe reads, connector task publication, Queue consumption, delayed retries and scheduled outbox recovery.

The browser never receives the private upstream application origin or permanent server secrets.

## D. Durable connector objects

Runtime: Cloudflare R2 through the existing S3-compatible backend boundary.

Required backend configuration includes:

- `CONNECTOR_OBJECT_STORAGE_BACKEND=r2`
- `CONNECTOR_OBJECT_BUCKET`
- `CONNECTOR_OBJECT_ENDPOINT_URL`
- `CONNECTOR_OBJECT_REGION=auto`
- `CLOUDFLARE_R2_ACCESS_KEY_ID`
- `CLOUDFLARE_R2_SECRET_ACCESS_KEY`

The application verifies size and SHA-256 metadata before accepting a durably staged connector upload. Tenant and connection namespaces include collision-resistant scope suffixes. Scoped reads verify checksum and exact tenant/connection metadata.

## E. Durable connector tasks

Runtime: Cloudflare Queues.

Primary queue:

`agroai-connector-tasks`

Dead-letter queue:

`agroai-connector-tasks-dlq`

The API commits a connector job and transactional outbox row atomically. The outbox drainer claims publishable rows, the API/edge publishes bounded task envelopes, Queue consumers call the protected backend processor, worker ownership fences completion, retries are bounded, and exhausted messages move to the dead-letter queue. A scheduled Worker recovers pending outbox rows and object-GC work.

Required shared tokens remain server-side:

- `QUEUE_PUBLISH_TOKEN` / backend `CLOUDFLARE_QUEUE_PUBLISH_TOKEN`
- `QUEUE_CONSUMER_TOKEN` / backend `CLOUDFLARE_QUEUE_CONSUMER_TOKEN`

## F. Local AI runtime

Public model gateway:

`local-ai.agroai-pilot.com`

Runtime path:

Cloudflare named tunnel `agroai-local-ai` → local model runtime.

This path remains separate from the public API edge. The repository does not assume an interactive terminal is sufficient for production persistence.

## F2. Platform API backend

Runtime: the production FastAPI backend behind the existing Cloudflare API edge.

Authoritative source:

`agroai_api/`

Namespace:

`/v1/platform/*`

The production Platform master API is already an established deployment surface. Public TEST self-service is a separate activation state layered on the tested control-plane and entitlement architecture.

### Public TEST flags

The protected activation workflow may enable only this TEST developer path:

- `PLATFORM_API_ENABLED=true`
- `PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED=true`
- `PLATFORM_API_TEST_PROJECTS_ENABLED=true`
- `PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED=true`
- `PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED=true`
- `PLATFORM_API_TERMS_ENFORCEMENT_ENABLED=true`
- `PLATFORM_API_CLI_DEVICE_AUTH_ENABLED=true`
- `PLATFORM_API_PUBLIC_DOCS_ENABLED=true`

The launch workflow explicitly writes the following dangerous or commercially separate capabilities to `false`:

- `PLATFORM_API_LIVE_PROJECTS_ENABLED`
- `PLATFORM_API_LIVE_ACCESS_REQUESTS_ENABLED`
- `PLATFORM_API_WEBHOOK_DELIVERY_ENABLED`
- `PLATFORM_API_LIVE_AUTO_APPROVAL_ENABLED`
- `PLATFORM_API_BILLING_ENABLED`
- `PLATFORM_API_STRIPE_CHECKOUT_ENABLED`
- `PLATFORM_API_STRIPE_METER_EXPORT_ENABLED`
- `EARTHDAILY_ADAPTER_ENABLED`
- `VALLEY_IRRIGATION_ADAPTER_ENABLED`
- `VALLEY_IRRIGATION_WRITE_CAPABILITY_ENABLED`

TEST projects never become LIVE projects in place.

### Production security prerequisites

Before public TEST traffic, production must retain:

- non-default application signing secret;
- `PLATFORM_API_KEY_PEPPER` outside the database;
- Redis-backed Platform rate limiting;
- rate-limit fail-open disabled;
- matching trusted edge/origin authentication secret;
- production PostgreSQL schema at the expected Alembic head;
- production credential-vault readiness;
- exact release-SHA proof;
- operational email verification delivery;
- current effective legal catalog;
- CLI device-auth secret readiness.

The authenticated Playground is browser-session mediated and TEST-only. Permanent API keys do not enter browser JavaScript. It operates on deterministic synthetic data and cannot reach LIVE providers or physical actions.

EarthDaily and Valley remain `awaiting_partner_contract` until their separate official documentation, credentials, contract and production proof gates are satisfied. Valley physical command execution remains disabled.

## F3. Public TEST legal gate

Public auto-enrollment is fail-closed on real legal approval evidence.

Draft legal review material lives under:

`platform-api/legal/drafts/`

It is explicitly NOT EFFECTIVE.

Public activation requires:

- `platform-api/legal/approved-catalog.json` with `status: counsel_approved`;
- reviewer, approval reference and approval timestamp;
- exact versioned HTML assets under `platform-api/assets/legal/`;
- exact SHA-256 digests matching those assets;
- matching production `approved_effective` Platform terms records.

`platform-api/legal/validate_approved_catalog.py` validates this evidence but cannot create or infer legal approval.

## F4. Public CLI distribution

The official Python CLI can be installed without a package registry.

macOS/Linux:

```bash
curl -fsSL https://agroai-pilot.com/platform-api/assets/install.sh | sh
```

Windows PowerShell:

```powershell
iwr https://agroai-pilot.com/platform-api/assets/install.ps1 -UseBasicParsing | iex
```

The installers fetch the official public repository source archive and create an isolated Python environment without root/administrator privileges. PyPI, npm and Homebrew remain optional distribution channels and must not be advertised until namespace ownership and release credentials are verified.

After public TEST activation, the shortest terminal journey is:

```bash
agroai login
agroai --json bootstrap --name "First AGRO-AI integration"
export AGROAI_API_KEY="agro_test_..."
agroai doctor
agroai fields list --json
```

`bootstrap` creates TEST project → TEST-safe service account → one-time TEST key. It does not request LIVE, provider-write or physical-action permission.

## G. Release pipeline

Authoritative general production workflow:

`.github/workflows/deploy.yml`

It validates Portal and Platform builds, localization, edge contracts, backend readiness, exact schema and immutable backend release identity, Queue/object-store/vault/rate-limit readiness, then deploys Cloudflare edge/Queues and Pages and performs production smoke verification.

Platform marketing/public-state workflow:

`.github/workflows/deploy-platform-api-marketing.yml`

It deploys the narrow Platform marketing Worker and proves landing/docs/installers, genuine unknown-route 404 behavior, standalone product identity, exact backend release SHA, Redis/vault/edge readiness and the public/private product-state contract.

The workflow reads the durable GitHub Actions variable `PLATFORM_API_PUBLIC_SELF_SERVICE_LAUNCHED`. When false/unset it deploys private-beta copy and noindex. When true it deploys public TEST self-service copy and indexing and requires effective legal terms plus ready CLI device auth.

Protected public activation workflow:

`.github/workflows/platform-api-public-self-service-activation.yml`

It runs only from current `main`, requires the production GitHub environment, validates real counsel evidence, performs two-stage Render configuration/deployment, publishes exact effective legal records, enables only TEST self-service flags, explicitly disables LIVE/provider/webhook/physical/billing flags, deploys public marketing/indexing mode, persists the public-launch variable and stores activation evidence.

Protected public rollback workflow:

`.github/workflows/platform-api-public-self-service-rollback.yml`

It disables new public auto-enrollment and CLI device acquisition, restores private-beta marketing/noindex, keeps dangerous capabilities off, and preserves existing projects/keys/enrollments for auditability.

A successful branch build is not production activation. Public TEST self-service may be described as live only after the protected activation workflow and exact production smoke gates succeed.

## H. Emergency rollback

General Cloudflare rollback remains owned by:

`.github/workflows/cloudflare-rollback.yml`

Platform public-acquisition rollback is owned by the separate public-self-service rollback workflow above. Neither rollback is allowed to turn on LIVE or physical capabilities.

## I. Safety rules

- Do not route the API edge upstream to its own public hostname.
- Do not expose Queue tokens, provider credentials, permanent Platform API keys, signing secrets or peppers to browser bundles.
- Do not duplicate authentication or Platform persistence for the standalone developer product.
- Do not let browser/client input choose organization entitlement, environment, quota or privileged scopes.
- Do not let TEST enrollment grant LIVE projects, production provider credentials, billing, production webhook delivery or physical execution.
- Do not activate public self-service with draft or unapproved legal documents.
- Do not advertise registry installation until the package namespace and publishing credential are actually controlled.
- Do not enable production webhook delivery before its separate staging/network delivery proof.
- Do not claim EarthDaily or Valley production readiness while provider contract gates remain unsatisfied.
- Do not claim enterprise SLA evidence before the required elapsed SLO history exists.
- Do not claim SOC 2, ISO or equivalent compliance evidence before the independent assessment/certification exists.
- Do not claim production activation until the exact deployed release passes the authoritative production workflows.

## J. Current activation truth

Repository capability and public production activation are separate facts.

The repository contains the complete tested public TEST self-service implementation, public installer paths, protected activation/rollback machinery and fail-closed legal evidence boundary.

Until real counsel approval evidence is committed and the protected production activation workflow succeeds, public acquisition remains in the private-beta/noindex state. That external approval requirement must not be bypassed, fabricated or replaced with a code assertion.

LIVE projects, provider production writes, production webhook delivery, physical execution, enterprise SLA claims and compliance claims remain separately gated regardless of TEST self-service state.
