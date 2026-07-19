Closes nothing — tracks #254 (Launch Field Intelligence: production activation and product completion). **Draft: do not merge, do not enable auto-merge, do not deploy, do not activate production.**

## Stage A — production activation readiness

- **Controlled rollout control plane** (migration `024_field_intelligence_launch`): server-side release states `disabled`/`internal`/`canary`/`general`; audited DB release override; **emergency kill switch** (immediate, audited, pauses processing while deletion/orphan-cleanup keep running); canary/internal cohorts from secure config CSVs or per-org `field_intelligence.rollout` entitlement overrides — no hardcoded IDs, and a plan update can never grant `general`. Enforced as a router-level dependency on every FI route, after the canonical account/organization boundary. Default production state: **disabled**.
- **Exact-SHA release alignment**: API build SHA, SHA-bearing worker heartbeats, portal/edge SHAs from the deploy pipeline and the DB revision must agree; `general` degrades to `canary` on mismatch in production and readiness blocks activation.
- **Worker topology**: dedicated graceful worker process (`scripts/run_field_intelligence_worker.py`) with liveness file, heartbeats (`field_worker_heartbeats`), queue-depth/stale gauges, multi-instance safety; admin fleet view.
- **Real transcription provider**: OpenAI-compatible whisper multipart adapter (configurable timeout, bounded input, multilingual detection with language provenance); production readiness fails truthfully on fakes, missing object storage, missing ffprobe or unreported release SHAs.
- **Database rollout**: `scripts/field_intelligence_migration.py` preflight/upgrade/verify/downgrade/verify-rollback (advisory-locked on PostgreSQL), validating tables, FKs, indexes, uniques, status domains and tenant lineage. Proven `022 → 024 → 022 → 024` on PostgreSQL 16 and SQLite. Runbook: `docs/field-intelligence-launch-runbook.md`.
- **Observability**: `agroai_field_*` Prometheus series (captures, upload bytes/latency, media rejections, quota refusals, queue depth, stale jobs/leases, stage latency, outcomes, retries, sync, deletions, reconciliation, rollout decisions by cohort, emergency disable) + centrally redacted structured events — no transcripts, tenant ids, object paths or secrets in labels/logs.
- **Canary smoke**: manually-gated 20-step script (`scripts/field_intelligence_canary_smoke.py`) covering capture → durability → processing → intelligence → task → range retrieval → deletion → audit → restricted-user blocking.

## Stage B — product completion

- **Model-routed extraction** through the existing ModelRouter with hard grounding (numbers must appear in the note; field/block/crop matched against authorized workspace vocabulary; model can never set timestamps; ungrounded people dropped; uncertainty caps confidence), truthful deterministic fallback with provenance (`method`, `prompt_version`, provider/model, `fallback_reason`); multilingual passthrough.
- **Expanded correlation** (schema 1.2.0): weather/ET + soil telemetry with honest freshness windows, block geometry, recent decisions, recently completed tasks, satellite evidence, missing-evidence derivation, `verification_required`.
- **Portal**: real lazy-loaded MapLibre map (backend style URL, severity-colored clustered pins, timeline-synchronized selection, accessible fallback); authenticated media players/gallery/download (no permanent public URLs); pre-submission draft review with retake/attachment removal and hardened MediaRecorder lifecycle (15-min cap, stop/save race awaited, stream release); installable **PWA shell** that caches only static assets (never `/v1/`, never non-GET, never cross-origin) with versioned cleanup and user-consented updates; global **sync center** with recovery drawer (retry/inspect/export/discard, identity-namespaced). EN/FR i18n parity held; 34-check launch portal contract in CI.
- **Commercial packaging** (documented in `docs/field-intelligence-commercial-matrix.md`): model extraction + audit become paid capabilities; Free gains a deliberate 25 voice-notes/month cap (replay-safe); storage tiers 512MB→100GB. Billing/Stripe untouched.
- **Admin operations**: platform-admin surface for rollout controls, kill switch, worker fleet, queue health, per-tenant usage/storage/failures, deletion queue, reconciliation and rollout audit (org-isolated).

## Validation (local)

- Complete backend suite: see checks on this PR (durable log wrapper locally).
- FI core/hardening/launch/object-storage/commercial: 129 passed; PG concurrency 3 passed; migration chain proven on PostgreSQL 16 + SQLite.
- Portal: launch contract 34 checks, offline multi-tab contract, full i18n chain, production build — pass. Edge gateway: 20 tests pass.
- Startup smoke 364 routes, zero new duplicates; `git diff --check`, conflict-marker and secret scans clean.

## External human-only configuration

R2 bucket + scoped credentials; transcription provider endpoint/key; deploy pipeline exporting `GIT_SHA`, `FIELD_RELEASE_PORTAL_SHA`, `FIELD_RELEASE_EDGE_SHA`; canary organization IDs; the pre-existing `lamine-github-io` Cloudflare Pages project build failure must be fixed or isolated in the Cloudflare dashboard before public activation.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
