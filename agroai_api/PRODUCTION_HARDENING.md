# AGRO-AI production process topology

This document describes the deployable hardening architecture implemented on
`platform-production-hardening` and aligned to the Cloudflare release path.

## Processes

### Release migration

Run exactly once per release, before new application code receives production
traffic:

```bash
alembic upgrade head
```

Web processes and task consumers must never create or repair managed schema at
request time. Production startup serializes migration execution and verifies the
repository/database Alembic head contract before application service.

### Web/API

```bash
uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
```

The API remains the authoritative FastAPI/SQLAlchemy application. In-process
scheduling must remain disabled. Public browser traffic enters through the
Cloudflare Worker edge gateway on `api.agroai-pilot.com/v1/*`.

The runtime error boundary and CORSMiddleware use the same exact origin policy;
lookalike Pages hostnames are rejected on both normal and exception paths.

### Connector task execution

Production connector jobs use Cloudflare Queues. The queue consumer delivers an
exact bounded task envelope to the protected API route:

`POST /v1/internal/queue/connector-task`

Supported task types are deliberately closed:

- `connector_ingest_object`
- `connector_provider_sync`

The route and the compatibility worker both call
`app.services.connector_task_processor.process_connector_task`, so transport
selection cannot fork connector business semantics. Unknown task types fail
closed before a database session is opened.

The legacy Redis consumer remains available for isolated compatibility and
integration testing; it is not required when `TASK_QUEUE_BACKEND` selects
Cloudflare Queues.

## Required production dependencies

### PostgreSQL

Use PostgreSQL as the system of record. Pool budgets must be sized across all
application processes. A release migration is a separate step.

### Cloudflare Queues

Required backend variables:

- `TASK_QUEUE_BACKEND=cloudflare_queues`
- `CLOUDFLARE_QUEUE_PUBLISH_URL`
- `CLOUDFLARE_QUEUE_PUBLISH_TOKEN`
- `CLOUDFLARE_QUEUE_CONSUMER_TOKEN`

Required Worker secrets:

- `QUEUE_PUBLISH_TOKEN`
- `QUEUE_CONSUMER_TOKEN`

The corresponding publish and consumer values must match across Worker and
backend secret stores. They must never be embedded in portal bundles.

Primary queue:

`agroai-connector-tasks`

Dead-letter queue:

`agroai-connector-tasks-dlq`

The Worker applies delayed retry to non-successful delivery, network errors,
invalid upstream configuration, and missing consumer custody. Only successful
application delivery acknowledges a message. Exhausted deliveries move to the
dead-letter queue.

### Durable connector object storage

Use a private Cloudflare R2 bucket:

- `CONNECTOR_OBJECT_STORAGE_BACKEND=r2`
- `CONNECTOR_OBJECT_BUCKET`
- `CONNECTOR_OBJECT_PREFIX`
- `CONNECTOR_OBJECT_REGION=auto`
- `CONNECTOR_OBJECT_ENDPOINT_URL`
- `CLOUDFLARE_R2_ACCESS_KEY_ID`
- `CLOUDFLARE_R2_SECRET_ACCESS_KEY`

Raw connector payloads are uploaded under server-generated tenant/connection
namespaces and verified by byte length and SHA-256 metadata before a job is
accepted as durably staged.

Namespace components combine a readable sanitized identifier with a SHA-256
scope suffix. This prevents distinct raw tenant or connection IDs from
collapsing into the same key prefix after sanitization. Scoped reads verify
checksum plus exact tenant/connection scope metadata. Staging cleanup deletes
are performed through the same scoped ownership contract.

The local upload directory is a transient bounded spool only; it is not the
production source of truth.

### Connector credential vault

Configure a 32-byte key encoded with URL-safe base64:

- `CONNECTOR_CREDENTIAL_MASTER_KEY`
- `CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION`

For rotation, configure a JSON keyring through
`CONNECTOR_CREDENTIAL_KEYS_JSON`, retain old key versions while rows are
re-encrypted, then remove retired versions only after migration is complete.

Connector credential payloads use AES-256-GCM with associated data bound to
tenant, connection, provider, and key version.

### OAuth state custody

Set a dedicated signing secret:

- `OAUTH_STATE_SIGNING_KEY`
- optional `OAUTH_STATE_TTL_SECONDS`

OAuth state is bound to tenant, connector, provider, callback digest, purpose,
expiry, and a random nonce. Only the nonce hash is persisted. Consumption is
atomic and one time.

### Local intelligence runtime

The current local model path is preserved:

`local-ai.agroai-pilot.com`
→ named tunnel `agroai-local-ai`
→ `127.0.0.1:11434`
→ Ollama
→ `qwen3:1.7b`

The API can use this endpoint through its AI gateway settings. The tunnel and
Ollama should be installed as persistent services rather than depending on an
interactive terminal session.

## Connector ingestion transaction flow

1. API streams request data to a bounded local spool and computes SHA-256.
2. API uploads the spool to private R2 storage.
3. API verifies object length, checksum, and scope metadata.
4. API creates an idempotent ingestion job and task-outbox row in one database transaction.
5. An outbox drainer atomically claims a publishable row as `publishing` before network I/O.
6. API publishes the claimed task through the protected edge enqueue endpoint.
7. The Worker validates the exact bounded task type and envelope and enqueues it.
8. The Queue consumer calls the protected backend delivery route.
9. The shared connector task processor claims the database job with an expiring lease.
10. A thread-owned heartbeat renews long-running leases; completion and failure updates require exact worker ownership.
11. The ingestion processor reads the durable object under the configured byte limit, verifies its checksum, parses, normalizes, and persists evidence.
12. Provider-sync records and cursor advancement remain staged until worker-owned fenced completion commits them.
13. Duplicate delivery resolves through tenant/connection/content identity and job idempotency.
14. Transient failures enter bounded delayed retry; exhausted Queue deliveries move to the dead-letter queue.
15. A five-minute Worker cron calls the protected maintenance route so publish-time outages do not strand committed jobs and eligible durable objects are garbage-collected.
16. Stale `publishing` claims recover after a bounded timeout. Because a crash after remote Queue acceptance but before local publication commit can still duplicate delivery, worker idempotency and lease fencing remain mandatory.

## Edge safety

The Worker edge gateway:

- allows only exact production origins plus approved Pages project origins;
- validates trusted request IDs against a bounded safe character contract;
- strips spoofable forwarding/internal headers;
- rejects an upstream that points back to the edge domain;
- proxies only `/v1/*`;
- retries only idempotent reads;
- cancels discarded transient retry response bodies;
- uses bounded timeouts;
- accepts only the two supported connector task types;
- retries instead of acknowledging when Queue consumer custody is missing;
- emits request IDs and security headers;
- fails closed when the upstream is invalid or unavailable.

The edge dependency graph is committed in
`cloudflare/edge-gateway/package-lock.json`. CI and release paths use `npm ci`
so a previously green release does not silently resolve a different transitive
toolchain.

## Route ownership

`/v1/evidence/upload-stream` has one authoritative customer implementation: the
hardened secure streaming route. The former duplicate legacy registration was
removed; the compatibility stream module now exposes only internal Queue router
composition and lazy compatibility imports used by the hardened handler.

## Release and rollback safety

The production release waits for an authenticated exact-SHA backend contract
before changing the public edge. That contract requires:

- exact runtime build SHA;
- exact Alembic repository/database heads;
- durable Queue configuration;
- configured and reachable object storage;
- zero production-readiness blockers.

Worker code and Queue secrets deploy together from a permission-restricted
temporary secrets file. Public smoke checks then prove edge health,
upstream-through-edge health, and the authenticated exact release contract.

Emergency Worker rollback is not accepted on edge health alone. It must also
prove upstream proxy health and the authenticated backend release contract.
Portal rollback targets an explicit prior successful Pages deployment. Release
and rollback evidence are retained as separate artifacts.

## Operational safety

The customer Intelligence surface uses the safe Brain route. Model output is
evaluated after generation. Claim-level provenance maps consequential statements
to concrete evidence records, and decision-class freshness rules prevent stale
or timestamp-unknown operational evidence from authorizing a current action.
High-impact execution remains disabled without explicit downstream approval
controls.

## Release checks

A release should not proceed when `/v1/readiness` reports blockers. The hardening
CI verifies migrations, connector custody, R2-compatible object storage,
Cloudflare Queue contracts, transactional outbox claims, lease heartbeat and
stale-worker fencing, exact route ownership, exact origin policy, partial-schema
rejection, multilingual intelligence, decision safety/provenance, enterprise
portal build, locked edge dependency installation, edge bundle validation, and
browser recovery lifecycle.

The production workflow additionally smoke-tests the exact deployed edge API and
portal and stores release evidence keyed by Git SHA.
