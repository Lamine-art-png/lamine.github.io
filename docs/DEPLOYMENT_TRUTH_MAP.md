# AGRO-AI Deployment Truth Map

This document is the authoritative release topology for the current platform.
It describes what the repository deploys and which boundaries own traffic. It
must be updated whenever routing or runtime ownership changes.

## A. Marketing Website

`agroai-pilot.com`

Runtime: Cloudflare Pages.

The marketing site is independent from the authenticated enterprise portal and
API release pipeline.

## B. Enterprise Portal

`app.agroai-pilot.com`

Runtime: Cloudflare Pages project `agroai-portal`.

Authoritative source application:

`figma-enterprise-v4/`

Production builds set:

`VITE_API_BASE_URL=https://api.agroai-pilot.com`

The browser must use the custom API domain. It must not learn or hardcode the
private upstream runtime origin.

## C. API Edge

`api.agroai-pilot.com/v1/*`

Runtime: Cloudflare Worker `agroai-api-edge`.

Authoritative source:

`cloudflare/edge-gateway/src/index.ts`

Responsibilities:

- exact browser-origin policy;
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

Authoritative Portal source for the gated developer control plane:

`figma-enterprise-v4/`

Namespace:

`/v1/platform/*`

Initial rollout state:

- `PLATFORM_API_ENABLED=false`
- `PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED=false`
- `PLATFORM_API_LIVE_PROJECTS_ENABLED=false`
- `PLATFORM_API_WEBHOOK_DELIVERY_ENABLED=false`
- `EARTHDAILY_ADAPTER_ENABLED=false`
- `VALLEY_IRRIGATION_ADAPTER_ENABLED=false`
- `VALLEY_IRRIGATION_WRITE_CAPABILITY_ENABLED=false`

Production requirements before external partner traffic:

- `PLATFORM_API_KEY_PEPPER` configured outside the database;
- `PLATFORM_API_RATE_LIMIT_BACKEND=redis`;
- `PLATFORM_API_REDIS_URL` or durable `REDIS_URL` configured;
- public OpenAPI explicitly enabled only when the curated route manifest is
  reviewed;
- developer control plane enabled only by the explicit
  `PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED` flag and then limited to
  organization owners/admins. Platform-admin status does not bypass this gate.

`EDGE_ORIGIN_AUTH_TOKEN` is activation-gated rather than an unconditional
Worker deployment prerequisite. When absent, the Worker still removes
caller-supplied edge identity headers and forwards no authoritative client IP;
CIDR-bound Platform API keys therefore fail closed. Production readiness
requires the matching `PLATFORM_API_EDGE_AUTH_SECRET` before
`PLATFORM_API_ENABLED=true`.

EarthDaily and Valley Irrigation are not live from this foundation. They remain
integration-readiness adapters with status `awaiting_partner_contract` until
official documentation, credentials, sandbox proof, provider calls, and
activation approval exist. Valley physical command execution is disabled.

## G. Release Pipeline

Authoritative workflow:

`.github/workflows/deploy.yml`

On `main` release it:

1. validates the enterprise portal;
2. installs the edge from the committed npm lockfile;
3. typechecks and tests the edge gateway;
4. validates the Wrangler deployment bundle against required-secret declarations;
5. compiles the backend and runs focused Queue, outbox, lease, object-storage, route, and readiness tests;
6. fails closed if required production release values are absent;
7. verifies current upstream health;
8. waits for the exact backend Git SHA, exact Alembic schema, Queue configuration, reachable durable object storage, and full production-readiness contract;
9. stores the upstream release-contract evidence artifact;
10. ensures the primary and dead-letter queues exist idempotently;
11. deploys Worker code and exact Queue secrets together from a mode-0600 temporary secrets file;
12. smoke-tests edge health, upstream-through-edge health, and the authenticated exact release contract;
13. builds the exact enterprise portal against the custom API domain;
14. deploys the portal to Pages;
15. smoke-tests the production portal;
16. stores immutable release evidence keyed by Git SHA.

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

- Do not route the Worker upstream back to `api.agroai-pilot.com`; recursion is
  rejected in code.
- Do not expose queue tokens to browser bundles.
- Do not enable the in-process API scheduler in production.
- Do not configure durable object storage without a durable task queue, or vice
  versa; upload routes fail closed on a split-brain configuration.
- Do not register a second customer `/v1/evidence/upload-stream` implementation;
  the hardened secure route is authoritative.
- Do not bypass Alembic schema ownership.
- Do not acknowledge Queue messages when consumer custody or upstream processing
  cannot be proven.
- Do not claim a deployment succeeded until the release workflow and production
  smoke checks succeed for the exact Git SHA.

## J. Platform API product surfaces (disabled)

The authoritative public marketing source is the root Cloudflare Pages project.
`/platform-api` and `/developers` are static assets guarded by Pages Functions
using server-side `PLATFORM_API_MARKETING_ENABLED` and
`PLATFORM_API_PUBLIC_DOCS_ENABLED`. Both default false, return 404 with
`noindex` while disabled, and are not present in navigation or sitemap.

The customer developer console remains inside `figma-enterprise-v4` at
`/developers/api`. Its navigation is granted only after the backend confirms
the developer-control-plane flag, approved organization, active owner/admin
membership, and active enrollment. Platform administrators use the separate
`/admin/platform-api` route.

API billing extends the existing backend but does not reinterpret Enterprise
Portal subscriptions. Stripe configuration is server-only and all API billing,
Checkout, meter export, pricing, Tax, support, status, applications, partner,
self-service, and live-access flags default false.

## K. Field Intelligence staging (isolated)

Field Intelligence staging is an entirely separate topology deployed only by
`.github/workflows/field-intelligence-staging.yml` through the protected
`field-intelligence-staging` environment. It must never target
`app.agroai-pilot.com`, `api.agroai-pilot.com`, `api-preview.agroai-pilot.com`,
the production Render service, production database, production R2 bucket, or
production Pages project. The launch migration is
`027_field_intelligence_launch` after `026_platform_api_operations`; staging
rollback proof is `027 → 026 → 027`, preserving the Field Intelligence
foundation and every Platform API program, commerce, and operations table.
The release state remains `internal` until a separately approved canary action.
See `docs/field-intelligence-staging-runbook.md`.
