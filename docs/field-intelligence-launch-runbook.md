# Field Intelligence — Production Launch Runbook

Authoritative procedure for taking Field Intelligence from merged code to a
controlled production activation.

## Release states

| State | Who can use Field Intelligence |
|---|---|
| `disabled` | Nobody |
| `internal` | Configured AGRO-AI internal/platform-admin operator organizations and explicit internal cohorts |
| `canary` | Internal + `FIELD_CANARY_ORGANIZATION_IDS` / `canary` rollout overrides |
| `general` | Everyone — **only** when exact-SHA release alignment holds |

Controls, in precedence order:

1. **Emergency kill switch** — `POST /v1/field-intelligence/admin/kill-switch`
   (platform admin; audited; immediate; pauses processing while deletion and
   orphan cleanup continue).
2. **DB release override** — `POST /v1/field-intelligence/admin/release-override`
   (platform admin; audited).
3. **Deployment config** — `FIELD_INTELLIGENCE_RELEASE_STATE`.

An unset release state remains fail-closed in production unless the server
already has a configured `PLATFORM_ADMIN_EMAILS` or
`INTERNAL_FULL_ACCESS_EMAILS` allowlist. In that case the effective default is
`internal`, and only organizations containing one of those server-authorized
operators are admitted. No browser claim, JWT role, plan update, or hardcoded
organization identifier can select that cohort. Ordinary customer
organizations remain locked.

A routine plan or entitlement update can never grant `general`:
per-organization `field_intelligence.rollout` overrides may only be `internal`
or `canary`.

## Environment contract

Required whenever Field Intelligence is active:

- durable R2/S3-compatible storage and scoped credentials;
- `ffmpeg`/`ffprobe` on the API image;
- a real transcription path;
- at least one live SHA-bearing Field Intelligence worker;
- PostgreSQL at repository Alembic head `027_field_intelligence_launch`.

### Voice transcription

Two production-safe Cloudflare Workers AI paths are supported:

1. **Direct account endpoint** — explicit `FIELD_TRANSCRIPTION_ENDPOINT`,
   `FIELD_TRANSCRIPTION_API_KEY`, and model. The backend accepts only the
   official account-scoped HTTPS `ai/run` URL matching the model.
2. **Protected AGRO-AI edge bridge** — when explicit transcription settings are
   absent in production/staging, the backend uses
   `CLOUDFLARE_QUEUE_CONSUMER_TOKEN` to call
   `https://api.agroai-pilot.com/v1/internal/edge/field-transcription`. The API
   edge validates that shared server credential, bounds and validates Base64
   audio, permits only `@cf/openai/whisper-large-v3-turbo`, invokes its existing
   Workers AI binding, and returns a no-store response. The browser never sees
   the credential and the edge never logs audio or transcript content.

Cloudflare Workers AI requests contain authorized durable audio bytes only;
they never contain R2 credentials, object keys, customer access tokens, or
unrelated workspace content.

For later `general` activation, `FIELD_RELEASE_PORTAL_SHA` and
`FIELD_RELEASE_EDGE_SHA` must be reported by the deployment pipeline so API,
worker, portal, edge, and database alignment can be proven.

## Browser capture contract

The enterprise portal must send a first-party device policy:

```text
Permissions-Policy: camera=(self), microphone=(self), geolocation=(self), payment=(), usb=()
```

Disabling microphone or geolocation at the document policy makes otherwise
correct `getUserMedia` and geolocation calls fail before the browser can prompt
the user. CI verifies that the production `_headers` file permits these
first-party capabilities while retaining all unrelated restrictions.

## Worker topology

The application starts the Field Intelligence worker when
`FIELD_INTELLIGENCE_WORKER_ENABLED=true`. It records exact-SHA heartbeats in
`field_worker_heartbeats`, uses fenced job leases and PostgreSQL advisory locks,
and is safe against duplicate claims.

The initial internal release may use the in-process worker on the existing API
service. Before broad/general activation or horizontal API scaling, deploy a
dedicated persistent worker and set `FIELD_INTELLIGENCE_WORKER_ENABLED=false`
on API replicas:

```bash
python -m scripts.run_field_intelligence_worker --liveness-file /tmp/fi-worker-alive
```

The disposable zero-payment Render staging proof also uses one in-process
worker because Render has no free background-worker instance.

## Database rollout

```bash
export DATABASE_URL=postgresql://…
python scripts/field_intelligence_migration.py preflight
python scripts/field_intelligence_migration.py upgrade
python scripts/field_intelligence_migration.py verify
# Rollback removes only the launch-control revision:
python scripts/field_intelligence_migration.py downgrade
python scripts/field_intelligence_migration.py verify-rollback
```

CI proves:

`026_platform_api_operations → 027_field_intelligence_launch → 026_platform_api_operations → 027_field_intelligence_launch`

The one-revision rollback preserves the Field Intelligence foundation and every
Platform API, verification, suspension, and appeal table/column.

## Internal production release procedure

1. Merge the exact green Field Intelligence PR into `main`.
2. The production backend auto-deploys the exact main SHA and runs Alembic under
   the migration lock.
3. The release workflow waits for exact backend SHA, current schema, durable
   object storage, Queue transport, and production readiness before changing
   public traffic.
4. Deploy the API edge and existing Workers AI binding from that same SHA.
5. Build and deploy `figma-enterprise-v4` to Cloudflare Pages project
   `agroai-portal` with that same SHA.
6. Verify `app.agroai-pilot.com`, public edge health, API health, microphone and
   location access, typed capture, voice capture, upload, processing, timeline,
   map, media retrieval, task creation, and deletion.
7. Keep effective state `internal`; ordinary customers remain locked.
8. Use the emergency kill switch immediately if object durability, tenant
   isolation, processing, or deletion evidence fails.

`general` remains a separate explicit decision and is never implied by this
internal production release.

## Observability

Prometheus `agroai_field_*` series cover captures, upload bytes/latency, media
rejections, quota refusals, queue depth, stale jobs/leases, stage latency,
processing outcomes/retries, sync batches, deletions, reconciliation, rollout
cohorts, and emergency disable. Labels and structured events never contain
tenant identifiers, transcripts, object paths, credentials, or customer media.

## Rollback

Trigger the kill switch first, then diagnose:

- sustained processing failure or queue growth;
- object-storage durability or deletion failure;
- any cross-tenant access finding;
- partial release or SHA misalignment.

The production workflow records immutable edge and portal evidence. Schema
rollback is a last resort and removes launch-control state; preserve required
Field Intelligence data before any destructive rollback.
