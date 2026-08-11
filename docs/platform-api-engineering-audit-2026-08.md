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
- App imports; 443 routes register.
- 39 CI-critical contract tests pass post-merge.
- Fail-closed defaults across all customer capabilities.
- No fabricated secrets/provider credentials/Stripe IDs.
- Key + webhook cryptography uses constant-time comparison and separated secrets.

## 7. Open verification/hardening backlog (honest — not yet done)

1. **Full slow unit suite** (119 files, DB-fixture heavy) — long-running verification in progress; must reach green.
2. **Real-PostgreSQL + real-Redis integration**: idempotency single-effect under concurrency; rate-limit distribution.
3. **BOLA/IDOR matrix** across every resource (fields, sources, observations, recommendations, reports, jobs, webhooks, keys, service accounts, billing).
4. **Secret-in-logs sweep**: assert no full key / provider token / webhook secret / Stripe secret reaches any log/metric/trace sink.
5. **OpenAPI ↔ SDK ↔ CLI contract drift** checks in CI.
6. **Production topology** (issue #378): prove replica count, pool sizing, Redis tier — code cannot fake this.
7. **Webhook delivery chain** proven in isolated staging before any flag change.
8. **DR**: verify actual PG PITR/backup + object-store versioning; run restore exercise.

## 8. Activation posture (see also final report)

| Gate | State | Basis |
|------|-------|-------|
| Safe to merge (this reconciliation) | **YES** | conflicts resolved additively; contracts pass; nothing destroyed |
| Safe for TEST self-service | **NOT YET** | full suite + integration verification pending; flags off |
| Safe for LIVE API use | **NO** | live flags off; Stripe/provider IDs unverified |
| Safe to enable webhook delivery | **NO** | must prove chain in staging first |
| Safe for physical execution | **NO** | fail-closed by design; separate approval required |
| Safe for enterprise SLA / compliance claim | **NO** | requires elapsed evidence + independent assessment (issues #378–#380) |
