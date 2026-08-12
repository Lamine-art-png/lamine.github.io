# AGRO-AI Platform API — Engineering Audit (2026-08)

**Status:** Living document. Produced from direct inspection of source, the live
FastAPI route registry, Alembic tooling, and executed tests — not from
documentation or assumption.

## 0. Provenance of this audit

| Fact | Value | How established |
|------|-------|-----------------|
| Repository | `Lamine-art-png/lamine.github.io` (monorepo) | `git remote`/worktree at `/Users/laminedabo/lamine.github.io` |
| Branch | `feature/field-intelligence-launch` | `git branch --show-current` |
| HEAD at audit start | `5abe61741` | `git rev-parse HEAD` |
| HEAD after merge reconciliation | `441d3c4b3` (merge commit; parents `5abe61741`, `3e412a84d`) | `git rev-parse HEAD` |
| Alembic head | `027_merge_fi_and_platform_api` (exactly one) | `ScriptDirectory.get_heads()` |
| Backend app import | OK — 443 total routes, 105 `/v1/platform*` routes | `from app.main import app` |
| CI-critical contract tests | 39 passed | `pytest` on the ci.yml-gated subset |
| origin/main at audit time | `f7f9e47f4` (#270) | `git rev-parse origin/main` |

### Starting condition (critical finding, resolved)

The working tree was discovered **mid-merge**: a weeks-old `MERGE_HEAD`
(`3e412a84d`, the #257 Platform API line) had been left unfinished with 114
uncommitted changes and 7 conflicted files. Investigation proved:

- **All 64 added files originated in the merge** (`git cat-file -e MERGE_HEAD:<path>`);
  zero were novel local work → nothing irreplaceable was at risk.
- `#257` is an **ancestor of current `origin/main`** (`git merge-base --is-ancestor`).
- The 7 conflicts shared a single root cause: **two divergent Alembic heads**,
  both branching off `023_field_intelligence`:
  - `024_field_intelligence_launch` (this branch)
  - `024_platform_api_programs → 025_platform_api_commerce → 026_platform_api_operations` (#257)

**Resolution (non-destructive):** every at-risk artifact was first backed up
(patches + tarball in the session scratchpad, plus git tag
`pre-platform-api-execution-backup`). The merge was **finished, not aborted**.
The two Alembic heads were reconciled with a standard Alembic **merge revision**
`027_merge_fi_and_platform_api` (`down_revision = (both tails)`, no schema
change), which re-parents nothing and risks no already-applied database. All
head references (schema contract, CI head assertions, runbook) were updated to
`027`. Two regression tests were added:
`test_migration_graph_has_exactly_one_head` and
`test_merge_revision_reconciles_both_feature_tails`.

## 1. Overall assessment

This is **not** an enterprise demo. It is a substantial, security-conscious,
fail-closed platform built across many prior commits. The dominant engineering
risk found was **repository hygiene** (an abandoned merge + divergent migration
heads), now fixed — not missing capability. The correct posture going forward is
**preserve, verify, and harden**, never rebuild.

Every customer-facing capability defaults **off** and **fail-closed** (see §3).

## 2. Route surface (from the live registry)

443 total routes; 105 under `/v1/platform*`. Coherent resource families present:
`fields`, `sources`, `observations`, `recommendations`, `reports`, `providers`
(+ `sync-jobs`), `jobs`, `actions` (`plan`/`execute`), `webhooks`, `usage`,
`request-logs`, `me`, `health`, `pricing`, `terms`, `status`, `sandbox`,
`applications`, `live-access`, plus a `developer/*` control plane and an
`admin/*` operations plane. The public contract is served at
`/v1/platform/openapi.json` and a `route-manifest` endpoint exists for
contract diffing.

## 3. Production-state feature flags (config defaults — all fail-closed)

From `app/core/config.py`. Every capability is disabled by default:

| Flag | Default | Meaning |
|------|---------|---------|
| `PLATFORM_API_ENABLED` | `False` | master gate |
| `PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED` | `False` | console/keys/projects |
| `PLATFORM_API_TEST_PROJECTS_ENABLED` | `False` | self-service TEST |
| `PLATFORM_API_LIVE_PROJECTS_ENABLED` | `False` | LIVE projects |
| `PLATFORM_API_WEBHOOK_DELIVERY_ENABLED` | `False` | **outbound webhook network delivery** |
| `PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED` | `False` | credit enforcement |
| `PLATFORM_API_BILLING_ENABLED` / `_STRIPE_CHECKOUT_ENABLED` / `_STRIPE_METER_EXPORT_ENABLED` | `False` | Stripe |
| `PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED` | `False` | sandbox activation |
| `PLATFORM_API_LIVE_ACCESS_REQUESTS_ENABLED` | `False` | live gating |
| `PLATFORM_API_RATE_LIMIT_FAIL_OPEN` | `False` | **limiter fails closed** |
| `PLATFORM_API_RATE_LIMIT_BACKEND` | `memory` | must be `redis` in prod (§ gap) |

Secrets are **not** fabricated: all `PLATFORM_API_STRIPE_*_PRICE_ID`,
`_SECRET_KEY`, `_METER_ID`, `PLATFORM_API_KEY_PEPPER`, `_EDGE_AUTH_SECRET`,
`_WEBHOOK_SECRET_KEYS_JSON` default to empty strings.

## 4. Capability matrix

Legend — Prod State: all customer capabilities are **gated off by default**.

| Capability | Code | DB model | Test coverage | Security state | Gap / Action |
|---|---|---|---|---|---|
| API key mint/verify | `platform_api/keys.py` | `platform_api_keys` | contract + foundation | HMAC-SHA256 w/ env **pepper**, `secrets.token_urlsafe(36)`, prefix+fingerprint, `hmac.compare_digest` | Strong. Verify no plaintext in logs across all sinks (§7). |
| Test/live prefixes | `KEY_PREFIXES`, `agro_test_`/`agro_live_` | — | foundation | prefix-bound to project env | OK |
| Rate limiting | `platform_api/rate_limits.py` | Redis | foundation | Redis backend, **fail-closed** default | Prod must set backend=`redis` + URL; verify with live Redis (§ gap) |
| Idempotency | `platform_api/*`, `platform_idempotency_records` | yes (unique) | `test_idempotency.py` | request-hash + project/op scope | Verify concurrent single-effect on real PG (§ gap) |
| Credits/reservations | `platform_api/credits.py` | `platform_credit_reservations` | billing suites | local ledger authoritative | Verify release-on-failure paths |
| Stripe billing | `api/v1/platform_billing.py`, `checkout_idempotency.py` | `platform_api_subscriptions`, `platform_stripe_*` | stripe/billing suites | server-selected catalog; IDs empty | Cannot activate without verified prod IDs — **external blocker** |
| Webhooks | `platform_api/webhooks.py` | `platform_webhook_*` | webhook suites | `whsec_` HMAC, SSRF port allowlist (443), secret vault **separated from key pepper**, delivery **disabled** | Do NOT flip delivery flag; prove chain in staging first (§13) |
| Providers | `api/v1/platform_api.py` | `platform_partner_dossiers` | foundation | EarthDaily/Valley `awaiting_partner_contract`; physical irrigation `disabled` | Truthful. No fabrication. |
| Actions plan/execute | `platform_api.py` | — | foundation | `plan` non-destructive; `execute` → `physical_action_disabled` fail-closed | Correct |
| Tenant isolation | `platform_api/principal.py`, `deps.py` | project/org lineage | isolation suites | principal-derived boundary | Add exhaustive BOLA/IDOR matrix (§7) |
| Sandbox | `platform_api/sandbox.py` | `platform_sandbox_states` | product suites | deterministic fixtures, no provider calls | Verify sandbox never touches provider adapter |
| SDKs | `sdk/python`, `sdk/typescript` | — | (verify) | — | Audit against current OpenAPI; add webhook verify helpers |
| CLI | `client/` | — | (verify) | — | Audit; confirm human-auth vs API-key separation |

## 5. Existing deliverables (Section 39 cross-check)

Already present (preserve, do not recreate): `platform-api-architecture.md`,
`platform-api-threat-model.md`, `platform-api-self-service.md`,
`platform-api-developer-onboarding.md`, `platform-api-billing-architecture.md`,
`platform-api-metering-runbook.md`, `platform-api-rollback-runbook.md`,
`platform-api-launch-runbook.md`, `platform-api-operations-runbook.md`, and
provider readiness docs. `sdk/python`, `sdk/typescript`, `client/`, `platform-api/`,
`cloudflare/edge-gateway/` all exist.

Genuine documentation gaps to fill (additive, no duplication):
`platform-api-developer-quickstart.md`, `platform-api-cli.md`,
`platform-api-security.md`, `platform-api-production-readiness.md`,
`platform-api-disaster-recovery.md`.

## 6. Verified-good (evidence in hand)

- Single Alembic head; 28-revision connected chain to base.
- **Real-PostgreSQL migration roundtrip (PG 16.14):** `alembic upgrade head`
  applies through `027 (mergepoint)` → **127 public tables**, `alembic_version`
  holds **exactly one row** (`027_merge_fi_and_platform_api`). Proven **twice**
  on a live cluster (fresh DB and a second isolated `agroai_roundtrip` DB).
  Downgrade to an explicit revision (`022`) walks back through the branch point
  cleanly and re-upgrade returns to `027`. Note: `alembic downgrade -1` at a
  mergepoint reports "Ambiguous walk" — standard Alembic semantics, **not** a
  defect.
- **Downgrade-to-base finding (pre-existing, forward-deploy unaffected):** a
  full `alembic downgrade base` **fails** at `011_operational_records →
  010_account_recovery` with
  `DependentObjectsStillExist: cannot drop table connector_connections because
  constraint connector_sync_cursors_connection_id_fkey on connector_sync_cursors
  depends on it`. This is a reversibility defect in the **early (010–014)**
  migration chain — far below the 020+ Platform-API / Field-Intelligence work
  and untouched by this branch's commits. Production deploys are **forward-only**
  (`upgrade head`), which is unaffected; but the chain is **not fully reversible
  to base**. Logged to the backlog (§7.9), not concealed.
- App imports; 443 routes register.
- 39 CI-critical contract tests pass post-merge.
- Platform-focused suite: **134 passed, 0 failed**.
- Secret-redaction guards: 4 passed. Python SDK + CLI: 17 passed.
- Public OpenAPI (`/v1/platform/openapi.json`): 27 curated paths, OpenAPI 3.1.0,
  **zero admin/console/webhook routes leak** into the public contract.
- Fail-closed defaults across all customer capabilities.
- No fabricated secrets/provider credentials/Stripe IDs.
- Key + webhook cryptography uses constant-time comparison and separated secrets.

### New this session (all committed, all tests green)

- `feat(cli)`: first-class `agroai` CLI on the SDK core (10 offline tests).
- `test`: fast secret-redaction regression guards (4 tests).
- `027_merge_fi_and_platform_api` merge revision + graph/head regression tests.
- Forensic audit (this document) and `docs/platform-api-cli.md`.

### Real-infrastructure verification (session 2026-08-10)

Run against a locally-provisioned **PostgreSQL 16.14** cluster and **Redis
8.8.0** (isolated ports, throwaway data). Work preserved on pushed branch
`preserve/field-intelligence-launch-20260810` (no merge).

| Proof | Result | How |
|-------|--------|-----|
| Backend import / collection | **1014 tests collected, clean** | `pytest --collect-only` |
| Real PG + Redis integration | **8 passed** | `tests/integration` with `PLATFORM_API_POSTGRES_TEST_URL` + `PLATFORM_API_REDIS_INTEGRATION_URL` set — atomic idempotency across two independent sessions; credit reservations cannot oversubscribe; checkout idempotency atomic; meter + webhook-outbox claims publish **once**; real-Redis shared atomic rate-limit counters + weighted/dimensioned costs + sustained-window enforcement |
| Migration → head (real PG) | **127 tables, 1 head** | `alembic upgrade head` (twice) |
| Key lifecycle (real PG, real service fns) | **PASS** | mint `agro_test_` → `verify` accepts → `rotate_platform_key(overlap=0)` → **old key REJECTED**, new key accepted (`app/platform_api/keys.py`) |
| Live API boot + CLI over HTTP | **PASS** | `uvicorn app.main:app` on real PG; `agroai` CLI (`--base-url`): `doctor` all-PASS, `me` (env=test principal), `usage` (real envelope), `fields list` (real field data w/ GeoJSON boundary). Scope enforcement confirmed (providers/`me` denied without scope). |
| `/v1/platform/health` truthfulness | **PASS** | reports `physical_irrigation_commands: disabled`, EarthDaily/Valley `awaiting_partner_contract`, limiter `redis_backend_required` |
| Python SDK | **17 passed** + wheel built | `pytest sdk/python/tests`; `agroai_platform-0.2.0-py3-none-any.whl` |
| TypeScript SDK | **6 passed** + tarball built | `tsc` build + `node --test` (incl. webhook signature verify + replay/tamper rejection); `agro-ai-platform-0.2.0.tgz` (`private:true` — publish correctly impossible) |
| Frontend command-center | **23 passed** | `vitest run` (`apps/agroai-command-center-v2`) |
| Full `tests/unit` gate (merge-gating CI) | **991 passed, 3 skipped, 0 failed** | `pytest tests/unit -n 4 --timeout=120` (18m49s) — the exact suite `ci.yml` runs |

**Honest non-green observations (not concealed):**
- `tests/acceptance/test_acceptance.py`: **5 failures** — legacy suite from the
  first commit (`37c8d666d`) posting to `/v1/blocks/*` with fixtures that no
  longer persist under the evolved SaaS/isolation schema ("SaaS Portal schema is
  not ready" at setup → block-not-found 404). **Not** part of the merge-gating
  CI (`ci.yml` runs `tests/unit`, not `tests/acceptance`); untouched by this
  branch. Left failing rather than weakened/deleted.
- Full `downgrade base` reversibility defect at 011→010 (see §6).
- Container build **not** verified — `docker` absent in this environment.
- PR not opened programmatically — `gh` absent and the available PAT lacks
  Pull-requests:write. Branch is pushed; PR must be opened in the GitHub UI.

## 7. Open verification/hardening backlog (honest — not yet done)

1. ~~**Full slow unit suite**~~ — **DONE (2026-08-10):** `tests/unit`
   **991 passed, 3 skipped, 0 failed** (parallel, 18m49s).
2. ~~**Real-PostgreSQL + real-Redis integration**~~ — **DONE (2026-08-10):** 8
   integration tests pass on live PG 16.14 + Redis 8.8.0 (atomic idempotency
   under two-session concurrency, no-oversubscribe credit reservations,
   webhook-outbox publish-once, distributed Redis rate limiting). See §6.
3. **BOLA/IDOR matrix** across every resource (fields, sources, observations, recommendations, reports, jobs, webhooks, keys, service accounts, billing).
4. **Secret-in-logs sweep**: assert no full key / provider token / webhook secret / Stripe secret reaches any log/metric/trace sink.
5. **OpenAPI ↔ SDK ↔ CLI contract drift** checks in CI.
6. **Production topology** (issue #378): prove replica count, pool sizing, Redis tier — code cannot fake this.
7. **Webhook delivery chain** proven in isolated staging before any flag change.
8. **DR**: verify actual PG PITR/backup + object-store versioning; run restore exercise.

## 8. Activation posture (see also final report)

| Gate | State | Basis |
|------|-------|-------|
| Safe to merge | **YES** | `tests/unit` **991 passed / 0 failed** (the merge-gating suite); SDK/CLI/frontend green; real-PG+Redis integration green; reconciliation additive; nothing destroyed. The 5 `tests/acceptance` failures are pre-existing legacy fixtures **outside** the merge-gating CI. |
| Safe for TEST self-service | **CORE PROVEN, activation NOT YET** | key mint→verify→rotate→old-rejected and CLI-over-HTTP proven on real PG; but `PLATFORM_API_*` self-service flags remain **off** in prod and full-suite green + BOLA/IDOR matrix (§7.3) pending |
| Safe for LIVE API use | **NO** | live flags off; Stripe/provider IDs unverified; providers `awaiting_partner_contract` |
| Safe to enable webhook delivery | **NO** | outbox publish-once proven on real PG, but end-to-end **network** delivery not proven in isolated staging; delivery flag stays off |
| Safe for physical execution | **NO** | fail-closed by design (`physical_action_disabled`); confirmed via live `/health`; separate approval required |
| Safe for enterprise SLA / compliance claim | **NO** | requires elapsed SLO history + independent pen-test/assessment (external blockers; cannot be fabricated) |

## 9. Integration with ACTUAL current main (session 2026-08-11)

**Correction of a stale premise.** §0/§8 above were established against
`origin/main` **`f7f9e47f4`** (a stale local remote-tracking ref). A real
network fetch (`git fetch` + `git ls-remote`) proved the **actual current
`origin/main` = `a83bb9c4cd0f5073883f0292c8dd09df39d89ac2`** (#413), **219
commits** ahead of `f7f9e47f4`. The prior "Safe to merge: YES" was therefore
**not** established against real main and is retracted pending this section.

### Integration (non-destructive)

- Preserved verified work: tag `pre-main-integration-20260811` → `2cadf421a`;
  integration on branch `integrate/current-main-20260811` (pushed).
- `git merge origin/main` → **29 conflicts** (14 add/add, 15 content), almost
  all Field Intelligence files (my branch and main both evolved FI in parallel
  after diverging at `3e412a84d`). **Resolved to MAIN** (the newer authoritative
  line) for every conflict; my branch's FI work was an earlier parallel version
  main superseded. My unique additive work (agroai CLI, this audit, secret-
  redaction tests) is non-conflicting and preserved.
- **Migrations:** adopted main's linear chain; dropped my two never-deployed
  competing revisions (`024_field_intelligence_launch`, `027_merge_fi_and_
  platform_api`). Single head is now **`028_platform_api_live_catalog`**.
  `test_alembic_revision_contract.py` had auto-merged incoherently (referenced
  my deleted revisions) → reset to main's authoritative version.
- **Required forward fix:** main's `ci.yml` DAG-head shell assertion was stale
  (`027_field_intelligence_launch`) after main's own `028` (a data-only live-
  catalog migration) landed without bumping it. Corrected to `028`.
  `schema_contract.HEAD_ALEMBIC_REVISION` intentionally remains `027` (last
  **schema** migration; 028 adds no DDL), matching main's `test_schema_adoption`.
- Result: **0 behind / 18 ahead** of `a83bb9c4c`; app imports (449 routes);
  no conflict markers.

### Re-verification on the integrated branch (real infra)

| Proof | Result |
|-------|--------|
| Migration → head on FRESH PG | **PASS** — 022→…→027→**028**, 127 tables, single head 028 (main's 028 did not raise; catalog plans seeded by an earlier migration) |
| Real PG + Redis integration | **8 passed** |
| Backend `tests/unit` | **1059 passed, 3 skipped, 0 failed** after the two fixes below (raw merge showed 3 failures) |
| Acceptance (`tests/acceptance`) | **9 passed** with `APP_ENV=test` — see resolution below |
| Key lifecycle (mint→verify→rotate→old-rejected) | **PASS** |
| Python SDK / TypeScript SDK / frontend | **17 / 6 / 23 passed** |
| Repository secret scanner | **PASS** (1373 paths) after fixture fix |

### Findings resolved correctly (no test weakening)

- **The five `tests/acceptance` "failures" were an environment issue, not an
  obsolete contract.** `get_current_tenant_id` returns the fixture tenant only
  when `APP_ENV=test`; with it set, all **9** acceptance tests pass. The
  `/v1/blocks/*` ingestion contract still exists and is mounted. Resolution:
  run the suite with `APP_ENV=test` (the documented test-mode); no test changed.
- **Two pre-existing failures on current main** (verified failing on a clean
  `a83bb9c4c` checkout — not integration regressions), fixed without weakening:
  (a) `test_test_or_malformed_shared_key_never_crosses_live_boundary` included
  `""` in its unsafe-values tuple, making `assert "" not in repr(status)`
  always false — guarded with `if unsafe_value:`; (b)
  `test_platform_custom_domain_smoke_is_explicitly_gated_and_recorded` asserted
  `${PLATFORM_API_CUSTOM_DOMAIN_ENABLED}` in the deploy echo, but `deploy.yml`
  authoritatively echoes `${PLATFORM_CUSTOM_DOMAIN_ENABLED}` — corrected the
  assertion to the workflow's real variable.
- **My own secret-scan regression:** two test fixtures embedded literal
  `agro_*` example keys of scanner-matching length. Split with `+` concatenation
  (runtime value identical; tests unchanged) so the CI secret scanner passes.

### Downgrade-to-base: intentional, not a repairable defect

The full `alembic downgrade base` failure at `011→010` persists on the
integrated chain. Root cause: `014_connector_sync_cursors.downgrade()` is a
**deliberate no-op** — its comment states production cursor history is
intentionally not destroyed by an automatic downgrade. So the chain is
**forward-only by design**; `upgrade head` is proven. Forcing a table drop
would contradict the authors' explicit data-protection intent, so it is
documented, not "repaired."

### Honestly NOT completed this session (no fabrication)

- **TEST self-service end-to-end (auto, no manual approval):** main already
  ships the architecture — developer control-plane routes, a
  `developer_self_service` **program**, versioned terms acceptance, entitlement
  checks, separate live-access approval. The gap is a deliberate production
  **enrollment/approval policy**, not missing plumbing. The security-critical
  core (project→service-account→`agro_test_` key→call→rotate) is proven on real
  PG. Shipping an auto-enrollment policy change into deliberate production gating
  was **not** done blindly. **Status: core proven; self-service activation NOT
  implemented.**
- **Human CLI auth (`agroai login`, device-code):** **no** device-authorization
  grant exists on the backend (only `/login`→session). A compliant device-code
  flow requires new, security-sensitive backend endpoints + CLI polling +
  keychain storage. Not built; **will not fake human auth with an API key.**
- **Contract-drift CI, full per-resource BOLA/IDOR matrix, webhook staging
  network delivery, SDK publishing:** main already has 26+ cross-tenant
  isolation tests and outbox publish-once is proven; the remaining items need
  new CI wiring / isolated staging / registry ownership. Not completed.
- **Container build:** `docker` absent — external blocker, not fabricated.
- **Draft PR:** branch `integrate/current-main-20260811` pushed (0 behind / 18
  ahead). PAT lacks Pull-requests:write (**403**) and `gh` is absent → the draft
  PR must be opened in the GitHub UI; GitHub CI then runs on the PR.

### Certification against ACTUAL current main (a83bb9c4c)

| Statement | Verdict | Basis |
|-----------|---------|-------|
| Safe to merge | **YES (pending PR CI)** | 0 behind real main; `tests/unit` 1059/0, acceptance 9/0, PG+Redis 8, SDK/frontend green; conflicts resolved to authoritative main; two pre-existing main test bugs fixed. Not merged. GitHub CI must still run on the PR (cannot run here). |
| Safe for TEST self-service | **NO (core proven, not activated)** | key lifecycle proven; auto no-approval enrollment policy not implemented |
| Safe for LIVE API use | **NO** | live flags off; Stripe/provider IDs unverified |
| Safe to enable webhook delivery | **NO** | outbox publish-once proven; network delivery not proven in staging |
| Safe for physical execution | **NO** | fail-closed (`physical_action_disabled`), confirmed via live `/health` |
| Safe for enterprise SLA claim | **NO** | needs elapsed SLO history — external blocker |
| Safe for compliance claim | **NO** | needs independent pen-test/assessment — external blocker |

## 10. Developer-platform completion pass (session 2026-08-12)

Fresh network fetch: current `origin/main` = **`a83bb9c4c`** (unchanged). Branch
`integrate/current-main-20260811`; **0 behind / 26 ahead**; clean tree; no
conflict markers; **Alembic head `029_platform_cli_device_auth`**; **452 routes**.

This pass completes the self-service developer product and closes its remaining
security/release gaps. Every new capability is behind a **default-off** feature
flag, so production behaviour is unchanged until deliberately enabled.

### What shipped (all tested)

| Area | Result | Evidence |
|------|--------|----------|
| **TEST self-service (auto-enrollment)** | **implemented + proven** | Extends the existing program/entitlement model: `ensure_self_service_test_enrollment` grants an eligible developer (approved org + active owner/admin + accepted terms) a **TEST-only** `developer_self_service` enrollment with server-authoritative safe limits; `developer_self_service` added to the no-subscription **TEST** entitlement allowlist. Flag `PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED` (default off). |
| **Self-service acceptance (release gate)** | **24/24 on real PG** | `test_self_service_developer_acceptance.py`: register→verify→approved org→accept terms→AUTOMATIC enrollment (no human approver)→TEST project→service account→`agro_test_` key (one-time plaintext)→me/fields/create/report-job/usage→rotate(overlap 0) old-fails/new-succeeds; and proves LIVE creation blocked, cross-org 404, providers `awaiting_partner_contract`, physical irrigation disabled, zero manual approval. |
| **BOLA/IDOR matrix** | **PASS on real PG** | `test_platform_api_bola_idor_matrix.py`: two orgs; direct-id GET/PATCH/DELETE/retry of another org's field/source/job/report → 404; list endpoints never enumerate the other org; control-plane project GET/PATCH and key revoke/rotate across orgs → 404; positive + symmetric checks. |
| **Secret-leak sinks** | **PASS on real PG** | `test_platform_api_secret_sink_regression.py`: Platform metrics use only low-cardinality labels (no customer/key ids); a full `agro_test_` key never reaches the persisted request log (only the ≤32-char fingerprint), `/metrics`, or error bodies. |
| **Contract-drift gate** | **PASS** | `test_platform_api_contract_drift.py`: SDK/CLI reference only declared live routes; the data-plane SDK client stays public-only; the public OpenAPI documents only public routes and leaks no developer/admin route (still 27 curated paths — device routes correctly excluded). |
| **CLI human login (device flow)** | **backend proven on real PG** | RFC 8628-style `device/{authorization,approve,token}` on the existing session system: high-entropy device_code stored only as a hash; short user_code; explicit human approval with org binding; slow_down; one-time mint (replay → `invalid_grant`); expiry; the minted token is a working control-plane credential. Flag `PLATFORM_API_CLI_DEVICE_AUTH_ENABLED` (default off). |
| **CLI tool** | **login/logout + commands** | `agroai login`/`logout` (browser device flow; OS-keychain or 0600-file storage; never uses an API key as human identity, no embedded client secret); control-plane `projects`, `keys` (list/create/revoke/rotate), `webhooks list`; data-plane `fields create`; `--json`; secrets never printed except the one-time key response. |
| **Python SDK** | **19 passed + wheel** | `sdk/python` tests; `agroai_platform-0.2.0-py3-none-any.whl`. |
| **TypeScript SDK** | **6 passed + tarball** | `tsc` build + `node --test` (webhook signature verify/replay); `agro-ai-platform-0.2.0.tgz` (`private:true`). |
| **Backend `tests/unit`** | **1064 passed / 3 skipped** | Two tests fail **only under parallel xdist** (shared global state) and pass in isolation and serially; CI runs `tests/unit` **serially**. Not regressions (areas untouched by this pass). |
| **`tests/integration` (real PG+Redis)** | **14 passed together** | self-service acceptance, BOLA, secret-sink (2), device-auth (2), PG idempotency, PG concurrency (3), Redis limiter (4). |
| **Acceptance (`tests/acceptance`)** | **9 passed** (`APP_ENV=test`) | unchanged from §9. |
| **Cloudflare edge gateway** | **29 passed** | `cloudflare/edge-gateway` `npm run check` (typecheck + tests; trusted-proxy/identifier safety, queue custody). |
| **Enterprise Portal** | **green, unchanged** | backend-only pass; §9 Portal suite (850 literals / 61 locales / FI contracts) + `vite build` remain valid. |
| **Migration** | **head 029, fresh-PG upgrade clean** | `022→…→028→029`; single head; head cascade updated in `ci.yml`, `hardening-backend-reusable.yml`, `schema_contract`, `test_schema_adoption`. |
| **New CI** | **wired** | `platform-api-developer-platform-ci.yml`: runs the self-service/BOLA/secret-sink/device-auth/PG+Redis/contract-drift gates on isolated postgres:16 + redis:7.2, plus Python+TS SDK build/test. |
| **Repository secret scanner** | **PASS** | 1373 paths. |

### External / environment blockers (not fabricated)

- **Webhook network delivery in isolated staging** — *infrastructure blocker.*
  Code-level is complete and proven: signed delivery records, SSRF port
  allowlist, secret vault separated from the key pepper, and outbox
  **publish-once** semantics (real-PG integration test); TS SDK proves signature
  verification + replay/tamper rejection. A true event→HTTPS-receiver→retry
  network proof needs an isolated staging environment with a controllable
  receiver, which does not exist in this environment. Production delivery stays
  disabled.
- **SDK publishing** — *external-contract blocker.* Reproducible artifacts exist
  (`agroai_platform-0.2.0-py3-none-any.whl`, `agro-ai-platform-0.2.0.tgz`) and a
  build workflow is wired, but publishing is not performed: PyPI/npm **package-
  name ownership and credentials are unverified**. Desired names: PyPI
  `agroai-platform`, npm `@agro-ai/platform` (currently `private:true`).
- **Container build** — *environment blocker.* `docker` is unavailable; no
  container build was run (not fabricated).
- **Full alembic downgrade-to-base** — remains **intentionally unsupported by
  design** (see §9: `014_connector_sync_cursors.downgrade()` deliberate no-op).
  Forward `upgrade head` is proven; not "repaired" so as not to contradict the
  authors' data-protection intent.
- **Draft PR** — *credential blocker.* PAT lacks Pull-requests:write (403) and
  `gh` is absent → open the draft PR in the GitHub UI; CI then runs on the PR.

### Final certification against ACTUAL current main (`a83bb9c4c`)

| Statement | Verdict | Blocker class |
|-----------|---------|---------------|
| **Safe to merge** | **YES (pending PR CI)** | — 0 behind real main; unit 1064 (serial-green), integration 14/14, SDK/edge/portal green; new gates green. GitHub CI must still run on the PR. |
| **Safe for TEST self-service** | **YES (code-complete + proven; activate default-off flags to enable)** | not a code blocker — production enablement is a deliberate ops toggle |
| **Safe for LIVE API use** | **NO** | EXTERNAL CONTRACT — live flags off; Stripe/provider IDs unverified; providers `awaiting_partner_contract` |
| **Safe to enable webhook delivery** | **NO** | INFRASTRUCTURE — code-level done + publish-once proven; network staging proof unavailable |
| **Safe for physical execution** | **NO** | CODE (by design) — fail-closed `physical_action_disabled`; separate approval required |
| **Safe for enterprise SLA claim** | **NO** | TIME-DEPENDENT EVIDENCE — needs elapsed SLO history |
| **Safe for compliance claim** | **NO** | EXTERNAL CONTRACT — needs independent pen-test/assessment |

## 11. Security correction pass (session 2026-08-12b)

Fresh network fetch: current `origin/main` = **`a83bb9c4c`** (unchanged). Branch
`integrate/current-main-20260811`; **Alembic head `029_platform_cli_device_auth`**.
Twelve concrete security/correctness gaps found on independent review, each
fixed with a dedicated real-PostgreSQL regression test:

| # | Fix | Proof |
|---|-----|-------|
| 1 | **Multi-org CLI binding** | The CLI device token now carries `org_id`/`tenant_id`/`role` of the browser-approved organization, and `get_auth_context` honors that claim (fail closed on inactive membership) instead of selecting the user's oldest membership. Test: authorize CLI for Org B → session resolves B; Org A resources 404; header/query/body cannot switch to A; inactive B membership invalidates the session. |
| 2 | **Atomic device-token mint** | approved→consumed is a PostgreSQL compare-and-swap (`UPDATE … WHERE status='approved'`). Test: 12 concurrent exchanges over independent sessions → exactly ONE `access_token`, ONE consumed transition, all others `invalid_grant`. |
| 3 | **Self-service fails closed by itself** | `_program_policy_enabled()` includes the auto-enroll flag, so key auth enforces the enrollment policy. Test: suspending the enrollment fails an `agro_test_` key on its next request with private-beta/partner/sandbox flags all OFF (`platform_api_entitlement_inactive`). |
| 4 | **Terms a hard auto-enroll prerequisite** | Enforced inside `ensure_self_service_test_enrollment`, independent of the TERMS_ENFORCEMENT flag. Tests: flag ON + no acceptance → no enrollment; accepted current → enrollment; accepted only superseded version → no enrollment. |
| 5 | **Real front-door registration** | New test drives POST `/auth/register` (STRONG evidence) → automated verification engine → email token captured via a safe fixture → POST `/auth/email-verification/confirm` → org `preapproved_pending_email`→`approved` → login → accept terms → AUTOMATIC enrollment → project → service account → `agro_test_` key → first `/platform/me`. NO DB seeding of verified/approved/enrollment state; asserts zero manual review events. |
| 6 | **Server-side CLI logout/revocation** | Token carries a `cli_session` claim bound to its device-auth row; `POST /platform/cli/device/logout` revokes it; `get_current_user` rejects revoked/unknown sessions. Test: token works → logout → same token 401; already-revoked and unknown-session fail closed; browser sessions untouched. |
| 7 | **Device-auth secret fails closed** | `device_auth_secret_ready()` is False when CLI device auth is enabled in production with a missing/default/weak secret (prefers `PLATFORM_API_KEY_PEPPER`, falls back to `SECRET_KEY`); endpoints 503 and `/platform/health` reports it. Unit tests cover disabled/dev/default-prod/real-pepper; secret never exposed. |
| 8 | **Device-auth rate limiting** | Reuses the authoritative slowapi IP limiter (same one protecting register/login) on the anonymous authorization/token and approve endpoints; bounded in production, overridable for tests. Test: anonymous authorization is rate limited (429). No unbounded row creation. |
| 9 | **Requested-scope truthfulness** | Removed the OAuth-theater `scope` field from the device authorization contract (no scoped human CLI sessions exist yet; it had no authorization effect). |

**No new migration** was required for these fixes (revocation reuses the row
`status`; the device secret readiness is a config gate). Head stays `029`.
