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
request time.

### Web/API

```bash
uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
```

The API remains the authoritative FastAPI/SQLAlchemy application. In-process
scheduling must remain disabled. Public browser traffic enters through the
Cloudflare Worker edge gateway on `api.agroai-pilot.com/v1/*`.

### Connector task execution

Production connector jobs use Cloudflare Queues. The queue consumer delivers a
bounded task envelope to the protected API route:

`POST /v1/internal/queue/connector-task`

The route and the compatibility worker both call
`app.services.connector_task_processor.process_connector_task`, so transport
selection cannot fork connector business semantics.

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

The Worker applies delayed retry to transient failures. Terminal application
outcomes acknowledge messages. Exhausted deliveries move to the dead-letter
queue.

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
3. API verifies object length and checksum metadata.
4. API creates an idempotent ingestion job and task-outbox row in one database
   transaction.
5. API immediately attempts to publish pending outbox rows through the edge
   gateway.
6. The Worker validates the bounded task envelope and enqueues it.
7. The Queue consumer calls the protected backend delivery route.
8. The shared connector task processor claims the database job with an expiring
   lease.
9. The processor reads the durable object under the configured byte limit,
   parses, normalizes, and persists evidence.
10. Duplicate delivery resolves through tenant/connection/content identity and
    job idempotency.
11. Transient failures enter bounded delayed retry; exhausted deliveries move to
    the dead-letter queue.
12. A five-minute Worker cron calls the protected outbox drain route so
    publish-time outages do not strand committed jobs.

## Edge safety

The Worker edge gateway:

- allows only exact production origins plus approved Pages project origins;
- strips spoofable forwarding/internal headers;
- rejects an upstream that points back to the edge domain;
- proxies only `/v1/*`;
- retries only idempotent reads;
- uses bounded timeouts;
- emits request IDs and security headers;
- fails closed when the upstream is invalid or unavailable.

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
Cloudflare Queue contracts, transactional outbox behavior, partial-schema
rejection, multilingual intelligence, decision safety/provenance, enterprise
portal build, edge bundle validation, and browser recovery lifecycle.

The production workflow additionally smoke-tests the exact deployed edge API and
portal and stores release evidence keyed by Git SHA.
