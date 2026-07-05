# AGRO-AI production process topology

This document describes the deployable hardening architecture implemented on `platform-production-hardening`.

## Processes

### Release migration

Run exactly once per release, before new web/worker replicas receive traffic:

```bash
alembic upgrade head
```

Web replicas and workers must never run schema creation or repair at request time.

### Web/API

```bash
uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
```

The web tier is expected to be horizontally replicated. In-process scheduling must remain disabled.

### Connector worker

```bash
python -m app.workers.connector_worker
```

Workers use Redis Streams consumer groups. Delivery is at least once. Database leases and ingestion idempotency prevent duplicate logical processing. A worker publishes pending transactional outbox rows before consuming work and can reclaim abandoned Redis messages after the configured lease interval.

Scale worker replicas independently from web replicas.

## Required production dependencies

### PostgreSQL

Use PostgreSQL as the system of record. Pool budgets must be sized across all web and worker replicas rather than per process in isolation. A release migration is a separate step.

### Redis Streams

Required variables:

- `TASK_QUEUE_BACKEND=redis_streams`
- `REDIS_URL`

Optional tuning:

- `TASK_QUEUE_STREAM` (default `agroai:tasks`)
- `TASK_QUEUE_GROUP` (default `agroai-workers`)
- `TASK_QUEUE_LEASE_SECONDS`
- `TASK_QUEUE_MAX_ATTEMPTS`

### Durable object storage

Use an S3 or R2-compatible private bucket:

- `CONNECTOR_OBJECT_STORAGE_BACKEND=s3` or `r2`
- `CONNECTOR_OBJECT_BUCKET`
- `CONNECTOR_OBJECT_PREFIX`
- `CONNECTOR_OBJECT_REGION`
- `CONNECTOR_OBJECT_ENDPOINT_URL` for R2 or another compatible endpoint

AWS-compatible credentials should be supplied through the platform's normal credential chain or secret environment. Raw connector payloads are uploaded under server-generated tenant/connection namespaces and verified by byte length and SHA-256 metadata before a job is created.

The local upload directory is a transient bounded spool only; it is not the production source of truth.

### Connector credential vault

Configure a 32-byte key encoded with URL-safe base64:

- `CONNECTOR_CREDENTIAL_MASTER_KEY`
- `CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION`

For rotation, configure a JSON keyring through `CONNECTOR_CREDENTIAL_KEYS_JSON`, retain old key versions while rows are re-encrypted, then remove retired versions only after migration is complete.

Connector credential payloads use AES-256-GCM with associated data bound to tenant, connection, provider, and key version.

### OAuth state custody

Set a dedicated signing secret:

- `OAUTH_STATE_SIGNING_KEY`
- optional `OAUTH_STATE_TTL_SECONDS`

OAuth state is bound to tenant, connector, provider, callback digest, purpose, expiry, and a random nonce. Only the nonce hash is persisted. Consumption is atomic and one time.

## Connector ingestion transaction flow

1. API streams request data to a bounded local spool and computes SHA-256.
2. API uploads the spool to private durable object storage.
3. API verifies object length and checksum metadata.
4. API creates an idempotent ingestion job and task-outbox row in one database transaction.
5. Worker publishes pending outbox rows to Redis Streams.
6. A worker claims the database job with an expiring lease.
7. Worker reads the durable object under the configured byte limit, parses, normalizes, and persists evidence.
8. Duplicate delivery resolves through the tenant/connection/content identity and job idempotency key.
9. Transient failures enter bounded exponential retry; exhausted jobs become terminal failures.

## Operational safety

The customer Intelligence surface uses the safe Brain route. Model output is evaluated after generation. Claim-level provenance maps consequential statements to concrete evidence records, and decision-class freshness rules prevent stale or timestamp-unknown operational evidence from authorizing a current action. High-impact execution remains disabled without explicit downstream approval controls.

## Release checks

A release should not proceed when `/v1/readiness` reports blockers. The hardening CI separately verifies PostgreSQL migrations, connector custody, object storage contracts, Redis queue behavior, partial-schema rejection, multilingual intelligence, decision safety/provenance, portal build, and the browser recovery lifecycle.
