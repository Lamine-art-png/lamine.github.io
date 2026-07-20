# Field Intelligence — Staging Runbook

Authoritative procedure for the isolated Field Intelligence staging
environment. **Nothing here may touch production**: `app.agroai-pilot.com`,
`api.agroai-pilot.com`, `api-preview.agroai-pilot.com` /
`agroai-api-preview.onrender.com` (the production upstream — "preview" in
name only), the `agroai-portal` Pages project, the production database,
bucket, secrets or customer accounts. These refusals are enforced by
`scripts/field_intelligence_staging_contract.py` and by hard checks inside
the staging workflow itself.

## Resource boundaries

| Surface | Production | Staging |
|---|---|---|
| Portal | Pages `agroai-portal` → app.agroai-pilot.com | Pages `agroai-portal-staging` (branch `field-intelligence-staging`, provider URL until DNS) |
| API | Render `agroai-api-preview` behind the CF edge | Dedicated staging service (e.g. Render `agroai-api-staging`), reached directly via its provider URL |
| Database | production PostgreSQL | dedicated staging PostgreSQL instance |
| Worker | production worker topology | staging worker service, or the staging API's in-process worker |
| Objects | production R2 bucket | dedicated staging bucket (name contains `staging`), prefix `staging/field-intelligence/`, staging-scoped keys |
| Transcription | production credential | staging-scoped credential |
| Release state | `disabled` until launch | `internal` (never `general`; `canary` needs `CONFIRM_STAGING_CANARY`) |

The staging portal build refuses production API URLs; the workflow refuses
the production portal project, production hostnames, the production DB
fingerprint and the production bucket name.

## Deployment order (all via the manually gated workflow)

Run **Field Intelligence Staging** (`workflow_dispatch` only) with:
`confirm=STAGE_FIELD_INTELLIGENCE`, `sha=<exact branch head>`, optional
`run_smoke=true`. The workflow, in order:

1. validates the confirmation, pins the SHA to the branch head, refuses main,
   and verifies PR #258 merge-ref CI is green for that head;
2. compiles and tests API, worker, portal (staging build) and edge;
3. validates the staging configuration contract (fail closed);
4. triggers the staging API deploy hook and waits until `/v1/health`
   reports the exact `build_sha`;
5. runs migration `preflight` → `upgrade` → `verify` against the staging DB;
6. proves rollback `024→022→024` on the disposable
   `fi_staging_rollback_proof` database on the same staging server (real
   staging smoke data is never destroyed for the proof);
7. deploys/starts the staging worker and waits for a fresh SHA-matching row
   in `field_worker_heartbeats`;
8. builds the portal with `VITE_API_BASE_URL=<staging API>`,
   `VITE_DEPLOYMENT_ENVIRONMENT=staging`, `VITE_BUILD_SHA=<sha>` and deploys
   it to `agroai-portal-staging`;
9. verifies release alignment + `internal` release state (refuses `general`);
10. optionally runs the 20-step smoke;
11. uploads immutable evidence artifacts (contract report, migration
    reports, rollback proof, smoke log, deployment metadata) keyed to the SHA.

## Internal-user setup

1. Create the founder/internal organization + account **on staging**.
2. Put its org id in `FIELD_STAGING_INTERNAL_ORGANIZATION_IDS` (environment
   secret; never in source) — this maps to the staging API's
   `FIELD_INTERNAL_ORGANIZATION_IDS`.
3. Set `PLATFORM_ADMIN_EMAILS` on the staging API to that account's email so
   the admin/rollout/kill-switch surface is reachable.
4. Mint `FIELD_STAGING_SMOKE_TOKEN` (internal account) and
   `FIELD_STAGING_RESTRICTED_SMOKE_TOKEN` (a suspended staging account).

## Smoke

```bash
FIELD_SMOKE_BASE_URL=<staging api> \
FIELD_SMOKE_TOKEN=… FIELD_SMOKE_RESTRICTED_TOKEN=… \
python agroai_api/scripts/field_intelligence_canary_smoke.py
```
Twenty steps, redacted output only, nonzero on any failure. In the workflow
it runs only with `run_smoke=true`.

## Emergency disable / rollback

- Kill switch (immediate, audited):
  `POST <staging api>/v1/field-intelligence/admin/kill-switch {"active": true}`
  as the platform-admin internal account. Deletion/cleanup jobs keep running.
- Release override: `POST …/admin/release-override {"state": "disabled"}`.
- Schema rollback (staging only, destroys staging FI data):
  `python scripts/field_intelligence_migration.py downgrade && … verify-rollback`.

## Evidence collection

Workflow artifacts `field-intelligence-staging-<sha>`: contract report,
migration preflight/upgrade/verify, rollback proof, smoke log, deployment
metadata. Retained 30 days; never contain tokens, transcripts or object keys.

## Cleanup

1. Kill switch on, then scale the staging worker/API to zero.
2. Drop staging databases (`…`, `fi_staging_rollback_proof`).
3. Empty and delete the staging bucket (staging credentials only).
4. Delete the `agroai-portal-staging` Pages deployment if desired.
5. Revoke staging tokens (Cloudflare, R2, transcription, smoke bearers).

## EXACT human provisioning checklist (one-time)

The workflow fails closed until every item exists:

1. **Staging API service** (e.g. Render): new service `agroai-api-staging`
   from this repo/branch, `Dockerfile` build, env per
   `agroai_api/.env.staging.example` bottom section; copy its **deploy hook**
   → GitHub environment secret `FIELD_STAGING_DEPLOY_HOOK`; its public URL →
   environment variable `FIELD_STAGING_API_URL`.
2. **Staging PostgreSQL**: dedicated instance; URL →
   secret `FIELD_STAGING_DATABASE_URL`; also set
   variable `PRODUCTION_DATABASE_HOST_FINGERPRINT` to the production DB
   hostname (hostname only) for refusal checks.
3. **Staging R2 bucket** `agroai-field-staging` + staging-scoped token:
   secrets `FIELD_STAGING_OBJECT_ENDPOINT_URL`,
   `FIELD_STAGING_R2_ACCESS_KEY_ID`, `FIELD_STAGING_R2_SECRET_ACCESS_KEY`;
   variable `FIELD_STAGING_OBJECT_BUCKET`.
4. **Staging transcription credential**: secrets
   `FIELD_STAGING_TRANSCRIPTION_ENDPOINT`, `FIELD_STAGING_TRANSCRIPTION_API_KEY`;
   variables `FIELD_STAGING_TRANSCRIPTION_PROVIDER=openai_whisper`,
   `FIELD_STAGING_TRANSCRIPTION_MODEL`.
5. **Cloudflare Pages project** `agroai-portal-staging` + a staging-scoped
   API token (Pages write on that project only): secrets
   `CLOUDFLARE_STAGING_API_TOKEN`, `CLOUDFLARE_STAGING_ACCOUNT_ID`.
6. **GitHub environment** `field-intelligence-staging` (protected, required
   reviewers recommended) holding all of the above.
7. **Worker**: either set `FIELD_INTELLIGENCE_WORKER_ENABLED=true` on the
   staging API service, or create a second staging service running
   `python -m scripts.run_field_intelligence_worker` and store its hook as
   `FIELD_STAGING_WORKER_DEPLOY_HOOK`.
8. **Internal org + tokens** per "Internal-user setup" above
   (secrets `FIELD_STAGING_INTERNAL_ORGANIZATION_IDS`,
   `FIELD_STAGING_SMOKE_TOKEN`, `FIELD_STAGING_RESTRICTED_SMOKE_TOKEN`).
9. **Future DNS (optional, manual):** `api-staging.agroai-pilot.com` →
   staging API; a staging portal hostname. Never automated by this workflow.
