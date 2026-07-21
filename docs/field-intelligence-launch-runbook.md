# Field Intelligence — Production Launch Runbook

Authoritative procedure for taking Field Intelligence from merged code to a
controlled production activation. **Nothing here activates automatically.**

## Release states

| State | Who can use Field Intelligence |
|---|---|
| `disabled` | Nobody (default in production until explicit approval) |
| `internal` | Organizations in `FIELD_INTERNAL_ORGANIZATION_IDS` or with an `internal` rollout override |
| `canary` | Internal + `FIELD_CANARY_ORGANIZATION_IDS` / `canary` rollout overrides |
| `general` | Everyone — **only** when exact-SHA release alignment holds |

Controls, in precedence order:
1. **Emergency kill switch** — `POST /v1/field-intelligence/admin/kill-switch`
   (platform admin; audited via `security_audit_events`; immediate; pauses
   processing but deletion/orphan-cleanup keep running).
2. **DB release override** — `POST /v1/field-intelligence/admin/release-override`
   (platform admin; audited).
3. **Deployment config** — `FIELD_INTELLIGENCE_RELEASE_STATE`.

An unset release state means `disabled` in production/staging. A routine plan
or entitlement update can never grant `general`: per-organization
`field_intelligence.rollout` overrides may only be `internal` or `canary`.

## Environment contract (production)

Required when the release state is not `disabled` (validated by
`evaluate_production_readiness` and surfaced as blockers):

- `CONNECTOR_OBJECT_STORAGE_BACKEND=r2|s3|s3_compatible`, `CONNECTOR_OBJECT_BUCKET`,
  `CONNECTOR_OBJECT_ENDPOINT_URL` (https), R2 credentials
- A real transcription provider plus `FIELD_TRANSCRIPTION_ENDPOINT`,
  `FIELD_TRANSCRIPTION_API_KEY`, and `FIELD_TRANSCRIPTION_MODEL`; fakes are
  readiness blockers in production. Supported production adapters:
  - `cloudflare_workers_ai`: Base64 JSON to the official account-scoped
    `https://api.cloudflare.com/client/v4/accounts/<account-id>/ai/run/<model>`
    endpoint. The endpoint host, account path, and model suffix are validated
    before the token can leave the process. Recommended staging model:
    `@cf/openai/whisper-large-v3-turbo`.
  - `openai_whisper`: multipart OpenAI-compatible `/audio/transcriptions` API.
  - `http`: provider-neutral raw-audio adapter for an explicitly reviewed endpoint.
- `ffmpeg`/`ffprobe` on PATH (baked into both API images)
- For `general`: `FIELD_RELEASE_PORTAL_SHA` and `FIELD_RELEASE_EDGE_SHA`
  reported by the deploy pipeline

Cloudflare Workers AI requests contain the authorized durable audio bytes only;
they never contain R2 credentials, object keys, user tokens, or unrelated
workspace content. When no language hint is supplied, the model auto-detects it.

Tuning (safe defaults exist): `FIELD_ASSET_MAX_BYTES`, `FIELD_AUDIO_MAX_SECONDS`,
`FIELD_SYNC_MAX_BATCH`, `FIELD_SYNC_MAX_BODY_BYTES`,
`FIELD_STORAGE_RESERVATION_TTL_SECONDS`, `FIELD_PENDING_OBJECT_GRACE_SECONDS`,
`FIELD_RECONCILER_INTERVAL_SECONDS`, `FIELD_TRANSCRIPTION_TIMEOUT_SECONDS`,
`FIELD_TRANSCRIPTION_MAX_BYTES`, `FIELD_DELETION_RETENTION_DAYS`,
`FIELD_WORKER_*`, `FIELD_STALE_JOB_ALERT_SECONDS`.

## Worker topology

Run at least one dedicated worker per persistent environment:

```bash
python -m scripts.run_field_intelligence_worker --liveness-file /tmp/fi-worker-alive
```

- Graceful SIGTERM/SIGINT (finishes the tick in flight).
- SHA-bearing heartbeats in `field_worker_heartbeats`; instances and queue
  depth visible at `GET /v1/field-intelligence/admin/workers`.
- Multi-instance safe (job leases + PostgreSQL advisory locks).
- Set `FIELD_INTELLIGENCE_WORKER_ENABLED=false` on API replicas when the
  dedicated worker is deployed, so drains never depend on HTTP traffic.

The disposable zero-payment Render staging proof is an explicit exception: it
uses `FIELD_INTELLIGENCE_WORKER_ENABLED=true` in one free API service because
Render has no free background-worker instance. That topology is acceptable only
for the bounded smoke test; the process sleeps with the free web service and is
not a production topology.

## Database rollout

```bash
export DATABASE_URL=postgresql://…
python scripts/field_intelligence_migration.py preflight   # no writes
python scripts/field_intelligence_migration.py upgrade     # advisory-locked
python scripts/field_intelligence_migration.py verify      # tables/FKs/indexes/uniques/lineage
# Rollback (removes ONLY the launch-control revision):
python scripts/field_intelligence_migration.py downgrade
python scripts/field_intelligence_migration.py verify-rollback
```

Chain proven in CI and locally: `026_platform_api_operations` →
`027_field_intelligence_launch` → `026_platform_api_operations` →
`027_field_intelligence_launch`. The one-revision rollback preserves the Field
Intelligence foundation plus every Platform API, verification, suspension and
appeal table/column.

## Activation procedure

1. Deploy API + dedicated worker + portal + edge from ONE commit; the deploy
   pipeline exports `GIT_SHA`, `FIELD_RELEASE_PORTAL_SHA`, `FIELD_RELEASE_EDGE_SHA`.
2. Run migration `preflight` → `upgrade` → `verify`.
3. Confirm readiness: `evaluate_production_readiness` has no
   `field_intelligence.*` blockers; `GET /v1/field-intelligence/admin/rollout`
   shows `release_alignment.aligned: true`.
4. Set `FIELD_INTELLIGENCE_RELEASE_STATE=internal`; verify internal orgs only.
5. Run the manually-gated canary smoke as a canary-org user:
   `FIELD_SMOKE_BASE_URL=… FIELD_SMOKE_TOKEN=… python scripts/field_intelligence_canary_smoke.py`
   (20 steps; any failure aborts activation).
6. Move to `canary`; watch the dashboards below for at least one business day.
7. `general` only with explicit approval; the server refuses `general`
   while release alignment fails.

## Observability

Prometheus: `agroai_field_*` series (captures, upload bytes/latency, media
rejections, quota refusals, queue depth, stale jobs/leases, stage latency,
processing outcomes/retries, sync batches, deletions, reconciliation, rollout
decisions by cohort, `agroai_field_emergency_disable`). Labels never contain
tenant identifiers, transcripts, object paths or secrets; structured events
(`agroai.field_intelligence.events`) are centrally redacted.

## Rollback conditions

Trigger the kill switch first (immediate, audited), then diagnose:
- sustained processing failure rate, queue depth growth, or stale leases;
- object-storage durability or deletion failures;
- any cross-tenant access finding (sev-1: kill switch + incident process);
- release misalignment after a partial deploy.

Schema rollback (`downgrade` + `verify-rollback`) is a last resort and removes
launch-control state; export Field Intelligence data first when contractually
required before any broader destructive rollback.

## External human-only steps

- Provision R2 bucket + scoped credentials; set the env contract in the
  deployment platform (never in the repository).
- Provision the transcription-provider token directly in the deployment
  secret store. For Cloudflare Workers AI, use a token scoped to Workers AI
  Read/Edit in the intended Cloudflare account; never reuse an R2 S3 key.
- The `lamine-github-io` Cloudflare Pages project build fails on main today;
  fix or explicitly isolate it in the Cloudflare dashboard before public
  activation (it is not driven from this repository).
