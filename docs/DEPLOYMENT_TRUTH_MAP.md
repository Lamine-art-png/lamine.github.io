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
- request IDs and security response headers;
- removal of spoofable internal forwarding headers;
- fail-closed upstream configuration;
- recursion protection;
- bounded retry for idempotent reads only;
- separate longer timeout for intelligence routes;
- authenticated internal connector-task publication;
- Cloudflare Queue consumption and delayed retries;
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
connector job is accepted as durably staged.

## E. Durable Connector Tasks

Runtime: Cloudflare Queues.

Primary queue:

`agroai-connector-tasks`

Dead-letter queue:

`agroai-connector-tasks-dlq`

Flow:

1. The API commits the job and transactional outbox row.
2. The API publishes the pending row to the Worker internal enqueue endpoint.
3. The Worker validates the bounded task envelope and sends it to the Queue.
4. The Queue consumer delivers the task to the protected backend processing
   endpoint.
5. The backend runs the shared connector task processor.
6. Terminal outcomes acknowledge the message.
7. Transient outcomes retry with bounded delayed backoff.
8. Exhausted messages move to the dead-letter queue.
9. A five-minute Worker cron drains recoverable pending outbox rows.

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

## G. Release Pipeline

Authoritative workflow:

`.github/workflows/deploy.yml`

On `main` release it:

1. validates the enterprise portal;
2. typechecks and tests the edge gateway;
3. validates the Wrangler deployment bundle;
4. runs focused backend queue integration tests;
5. ensures the primary and dead-letter queues exist idempotently;
6. provisions Worker queue secrets;
7. deploys the API edge Worker;
8. smoke-tests edge and upstream API health;
9. builds the exact enterprise portal against the custom API domain;
10. deploys the portal to Pages;
11. smoke-tests the production portal;
12. stores immutable release evidence keyed by Git SHA.

## H. Safety Rules

- Do not route the Worker upstream back to `api.agroai-pilot.com`; recursion is
  rejected in code.
- Do not expose queue tokens to browser bundles.
- Do not enable the in-process API scheduler in production.
- Do not configure durable object storage without a durable task queue, or vice
  versa; upload routes fail closed on a split-brain configuration.
- Do not bypass Alembic schema ownership.
- Do not claim a deployment succeeded until the release workflow and production
  smoke checks succeed for the exact Git SHA.
