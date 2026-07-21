# AGRO-AI Deployment Truth Map

This document is the authoritative release topology for the current platform.
It describes what the repository deploys and which boundaries own traffic. It
must be updated whenever routing or runtime ownership changes.

## A. Marketing Website

`agroai-pilot.com`

Runtime: Cloudflare Pages.

The marketing site is independent from the authenticated products and API
release pipeline. Its Platform API landing page and documentation live under
`/platform-api` and remain guarded by server-side Pages Function flags.

## B. Enterprise Portal

`app.agroai-pilot.com`

Runtime: Cloudflare Pages project `agroai-portal`.

Authoritative source application:

`figma-enterprise-v4/`

The Enterprise Portal is the agricultural operating room: operations, Field
Intelligence, evidence, recommendations, reports, integrations, billing,
account security, and platform administration.

Production builds set:

`VITE_API_BASE_URL=https://api.agroai-pilot.com`

The browser must use the custom API domain. It must not learn or hardcode the
private upstream runtime origin.

## B2. Authenticated Platform API Product

Primary hostname:

`platform.agroai-pilot.com`

Controlled compatibility path:

`app.agroai-pilot.com/platform/*`

Runtime: the same reviewed Cloudflare Pages build as the Enterprise Portal,
selected by an exact host-aware router.

Authoritative source:

- `figma-enterprise-v4/src/app/components/PlatformApplicationGate.tsx`
- `figma-enterprise-v4/src/app/components/PlatformConsole.tsx`
- `figma-enterprise-v4/src/app/components/PlatformSafetyNotice.tsx`
- `figma-enterprise-v4/src/app/routes.tsx`

The standalone product reuses the existing AGRO-AI authentication,
organization verification, session, localization, API client, and Platform API
control-plane routes. It does not create a second authentication system or a
second API backend.

Product states:

1. signed-out users receive the secure AGRO-AI account flow with Platform-specific copy;
2. verified but unenrolled organizations receive the private-beta application;
3. submitted applications remain locked and expose a review timeline only;
4. approved active test enrollments expose the developer control plane;
5. live access remains a separate reviewed request;
6. physical irrigation execution remains separately disabled.

Application submission creates a review record only. It cannot create a
project, issue a key, activate billing, accept draft legal documents, enable a
provider, grant live access, or authorize a physical action.

The standalone Pages custom domain must be attached and reviewed in Cloudflare
before it is advertised. Repository readiness is not proof that the custom
domain is already active. Detailed topology and activation boundaries are in
`docs/platform-api-product-topology.md`.

## C. API Edge

Machine API:

`api.agroai-pilot.com/v1/*`

Same-origin authenticated product routes:

- `app.agroai-pilot.com/v1/*`
- `platform.agroai-pilot.com/v1/*`

Runtime: Cloudflare Worker `agroai-api-edge`.

Authoritative source:

- `cloudflare/edge-gateway/src/index.ts`
- `cloudflare/edge-gateway/src/edge-main-v3.ts`
- `wrangler.toml`

Responsibilities:

- exact browser-origin policy, including Portal and Platform product origins;
- bounded trusted request IDs and security response headers;
- removal of spoofable internal forwarding headers;
- fail-closed upstream configuration;
- recursion protection;
- bounded retry for idempotent reads only, with discarded retry bodies cancelled;
- separate longer timeout for intelligence routes;
- exact connector task-type validation;
- authenticated internal connector-task publication;
- Cloudflare Queue consumption and delayed retries;
- no acknowledgement when consumer custody is absent;
- scheduled recovery of pending transactional outbox rows.

The upstream application origin is configured as `UPSTREAM_API_ORIGIN` in
`wrangler.toml`. Browser code never receives it.

## D. Durable Connector Objects

Runtime: Cloudflare R2 through the application's existing S3-compatible object
storage boundary.

Required backend configuration:

- `CONNECTOR_OBJECT_STORAGE_BACKEND=r2`
- `CONNECTOR_OBJECT_BUCKET`
- `CONNECTOR_OBJECT_ENDPOINT_URL`
- `CONNECTOR_OBJECT_REGION=auto`
- `CLOUDFLARE_R2_ACCESS_KEY_ID`
- `CLOUDFLARE_R2_SECRET_ACCESS_KEY`

The application verifies uploaded object size and SHA-256 metadata before a
connector job is accepted as durably staged. Tenant and connection namespaces
use readable identifiers plus collision-resistant SHA-256 scope suffixes, so
lossy filename sanitization cannot collapse distinct tenant identities into the
same object prefix. Scoped reads verify checksum and exact tenant/connection
metadata. Cleanup deletes are issued through the same tenant/connection scope.

## E. Durable Connector Tasks

Runtime: Cloudflare Queues.

Primary queue:

`agroai-connector-tasks`

Dead-letter queue:

`agroai-connector-tasks-dlq`

Flow:

1. The API commits the job and transactional outbox row in one database transaction.
2. An outbox drainer atomically claims a publishable row as `publishing` before network I/O.
3. The API publishes the claimed row to the Worker internal enqueue endpoint.
4. The Worker validates the exact bounded task envelope and sends it to the Queue.
5. The Queue consumer delivers the task to the protected backend processing endpoint.
6. The backend runs the shared fail-closed connector task processor.
7. Long-running jobs renew leases; completion and failure updates are fenced by worker ownership.
8. Provider records and cursor advancement commit only through the worker-owned fenced completion.
9. Terminal outcomes acknowledge the Queue message.
10. Transient outcomes retry with bounded delayed backoff.
11. Exhausted messages move to the dead-letter queue.
12. A five-minute Worker cron drains recoverable pending outbox rows and object GC.
13. Stale `publishing` claims recover after a bounded timeout; workers remain idempotent because a crash after remote acceptance but before local publication commit can still duplicate delivery.

Required shared secrets:

- `QUEUE_PUBLISH_TOKEN`
- `QUEUE_CONSUMER_TOKEN`

The matching backend values are:

- `CLOUDFLARE_QUEUE_PUBLISH_TOKEN`
- `CLOUDFLARE_QUEUE_CONSUMER_TOKEN`

The backend publish URL is:

`https://api.agroai-pilot.com/v1/internal/edge/connector-tasks`

## F. Local AI Runtime

Public model gateway:

`local-ai.agroai-pilot.com`

Runtime path:

Cloudflare named tunnel `agroai-local-ai`
→ `127.0.0.1:11434`
→ local Ollama
→ `qwen3:1.7b`

This path remains intentionally separate from the public API edge Worker. The
API can use it as an intelligence provider through `AI_BASE_URL` without
exposing the Mac directly to the public internet.

Service persistence for the tunnel and Ollama is an operator/runtime concern;
the repository must not assume that an interactive terminal remains open.

## F2. Platform API Private Beta

Runtime: the existing production FastAPI backend behind the existing Cloudflare
API edge.

Authoritative backend source:

`agroai_api/`

Namespace:

`/v1/platform/*`

Public product surfaces:

- marketing and docs: `agroai-pilot.com/platform-api`
- authenticated application: `platform.agroai-pilot.com`
- machine API: `api.agroai-pilot.com/v1/platform/*`

The initial private-beta configuration may enable:

- `PLATFORM_API_ENABLED`
- `PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED`
- `PLATFORM_API_TEST_PROJECTS_ENABLED`
- `PLATFORM_API_APPLICATIONS_ENABLED`
- `PLATFORM_API_PRIVATE_BETA_ENABLED`
- `PLATFORM_API_PARTNER_PROGRAM_ENABLED`
- `PLATFORM_API_SUPPORT_ENABLED`

The following remain disabled until their separate launch gates are satisfied:

- `PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED`
- `PLATFORM_API_LIVE_PROJECTS_ENABLED`
- `PLATFORM_API_LIVE_ACCESS_REQUESTS_ENABLED`
- `PLATFORM_API_BILLING_ENABLED`
- `PLATFORM_API_STRIPE_CHECKOUT_ENABLED`
- `PLATFORM_API_STRIPE_METER_EXPORT_ENABLED`
- `PLATFORM_API_PRICING_ENABLED`
- `PLATFORM_API_SDK_DOWNLOADS_ENABLED`
- `PLATFORM_API_WEBHOOK_DELIVERY_ENABLED`
- `PLATFORM_API_TERMS_ENFORCEMENT_ENABLED`
- `PLATFORM_API_LIVE_AUTO_APPROVAL_ENABLED`
- `EARTHDAILY_ADAPTER_ENABLED`
- `VALLEY_IRRIGATION_ADAPTER_ENABLED`
- `VALLEY_IRRIGATION_WRITE_CAPABILITY_ENABLED`

Production requirements before external developer traffic:

- `PLATFORM_API_KEY_PEPPER` configured outside the database;
- `PLATFORM_API_RATE_LIMIT_BACKEND=redis`;
- `PLATFORM_API_REDIS_URL` or durable `REDIS_URL` configured;
- fail-open rate limiting disabled;
- matching edge-to-origin authentication secrets configured;
- public OpenAPI explicitly enabled only when the curated route manifest is reviewed;
- developer control plane limited to approved organization owners/admins with an active enrollment;
- exact production build, schema, Queue, object-storage, vault, rate-limit, and readiness proof.

The authenticated Playground is portal-session mediated and test-only.
Permanent API keys do not enter browser JavaScript. It operates on deterministic
synthetic data, records an audit event, consumes no production credits, and
cannot access live providers or physical actions.

`EDGE_ORIGIN_AUTH_TOKEN` is activation-gated rather than an unconditional Worker
deployment prerequisite. When absent, the Worker still removes caller-supplied
edge identity headers and forwards no authoritative client IP; CIDR-bound
Platform API keys therefore fail closed. Production readiness requires the
matching `PLATFORM_API_EDGE_AUTH_SECRET` before `PLATFORM_API_ENABLED=true`.

EarthDaily and Valley Irrigation are not live from this foundation. They remain
integration-readiness adapters with status `awaiting_partner_contract` until
official documentation, credentials, sandbox proof, provider calls, contracts,
and activation approval exist. Valley physical command execution is disabled.

## G. Release Pipeline

Authoritative workflow:

`.github/workflows/deploy.yml`

On `main` release it:

1. validates the Enterprise Portal and authenticated Platform product build;
2. validates localization and product-route preservation;
3. installs the edge from the committed npm lockfile;
4. typechecks and tests the edge gateway and exact origin policy;
5. validates the Wrangler deployment bundle against required-secret declarations;
6. compiles the backend and runs focused Queue, outbox, lease, object-storage, Platform, route, and readiness tests;
7. fails closed if required production release values are absent;
8. verifies current upstream health;
9. waits for the exact backend Git SHA, exact Alembic schema, Queue configuration, reachable durable object storage, and full production-readiness contract;
10. stores the upstream release-contract evidence artifact;
11. ensures the primary and dead-letter queues exist idempotently;
12. deploys Worker code and exact Queue secrets together from a mode-0600 temporary secrets file;
13. smoke-tests edge health, upstream-through-edge health, and the authenticated exact release contract;
14. builds the exact Pages application against the custom API domain;
15. deploys the Pages build;
16. smoke-tests `app.agroai-pilot.com`;
17. when the standalone custom domain is configured, smoke-tests `platform.agroai-pilot.com` and its `/v1/*` Worker route;
18. stores immutable release evidence keyed by Git SHA.

A successful build or branch preview is not proof of production activation.

The edge dependency graph is committed in
`cloudflare/edge-gateway/package-lock.json`; CI and release paths must use
`npm ci`, not resolve a fresh transitive graph.

## H. Emergency Rollback

Authoritative workflow:

`.github/workflows/cloudflare-rollback.yml`

Rollback is manual and requires the literal confirmation `ROLLBACK`, an incident
reason, and at least one explicit Worker version ID or Pages deployment ID.
A Worker rollback is not considered successful merely because `/v1/edge-health`
responds: it must also proxy `/v1/health` successfully and pass the authenticated
backend release contract including schema, Queue, object-storage reachability,
and production readiness. Rollback evidence is retained separately from release
evidence.

## I. Safety Rules

- Do not route the Worker upstream back to `api.agroai-pilot.com`; recursion is rejected in code.
- Do not expose queue tokens or permanent Platform API keys to browser bundles.
- Do not duplicate authentication or Platform API persistence for the standalone product.
- Do not let an application submission create a project, key, live enrollment, billing subscription, provider connection, or physical action.
- Do not enable the in-process API scheduler in production.
- Do not configure durable object storage without a durable task queue, or vice versa; upload routes fail closed on a split-brain configuration.
- Do not register a second customer `/v1/evidence/upload-stream` implementation; the hardened secure route is authoritative.
- Do not bypass Alembic schema ownership.
- Do not acknowledge Queue messages when consumer custody or upstream processing cannot be proven.
- Do not claim EarthDaily, Valley, public billing, live projects, or physical writes are active while their flags remain disabled.
- Do not claim a deployment succeeded until the release workflow and production smoke checks succeed for the exact Git SHA.

## J. Platform API Public Surfaces

The authoritative public marketing source is the root Cloudflare Pages project.
`/platform-api` and its documentation/reference assets are guarded by Pages
Functions using server-side `PLATFORM_API_MARKETING_ENABLED` and
`PLATFORM_API_PUBLIC_DOCS_ENABLED`.

Disabled or unknown routes return a genuine 404 with `noindex`; they do not
collapse into the landing page. Public documentation is generated from the
curated Platform API OpenAPI contract and must not invent endpoints, pricing,
provider readiness, certifications, uptime, latency, or live-access availability.
