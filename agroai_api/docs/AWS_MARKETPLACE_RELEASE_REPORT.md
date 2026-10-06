# AWS Marketplace release report

Status: **integration deployed and disabled; AWS Marketplace is not live.**
Last updated: 2026-10-06 18:20 UTC.

## Verified current facts (2026-10-06)

Release identity
- PR #536 merged as `a40e8a8c3ce603e66a7cc70a0d955fa4d49dd0ce` (PR head `8fe2ab9`).
- Main has since advanced to `0490f68cf9ea5db07a8b423b7679d3d90dd3e6a9` (PR #527), which contains `a40e8a8`.
- Cloudflare Production Release succeeded for both commits:
  - `a40e8a8`: https://github.com/Lamine-art-png/lamine.github.io/actions/runs/37491040422
  - `0490f68`: https://github.com/Lamine-art-png/lamine.github.io/actions/runs/37509379489
- `api.agroai-pilot.com/health`, `agroai-api-preview.onrender.com/health` and `app.agroai-pilot.com/deployment.json` all report `build_sha` `0490f68…`. The app was built at 2026-10-06T18:13:54Z, environment `production`.

Live endpoint behavior (production and preview, unauthenticated)

| Request | Status | Body |
|---|---|---|
| `GET /health`, `GET /v1/health` | 200 | `status: ok` |
| `POST /v1/marketplace/aws/register` | 503 | `AWS Marketplace onboarding is not enabled yet` |
| `POST /v1/marketplace/aws/link` | 401 | `Missing bearer token` |
| `GET /v1/marketplace/aws/status` | 401 | `Missing bearer token` |
| `GET /v1/marketplace/aws/status` with an invalid bearer | 401 | `Could not validate credentials` |

There is no `/ready` route; `/health` is the readiness signal.

Migrations
- The chain is linear: `042_market_data_plane → 043_aws_marketplace_registration → 044_aws_marketplace_linking → 045_intelligence_platform_v1`. There is a single head, and `schema_contract.HEAD_ALEMBIC_REVISION = 045_intelligence_platform_v1`.
- At `0490f68`, upgrade → downgrade to `042_market_data_plane` → upgrade passes on PostgreSQL 16 and on SQLite.
- `start-production.sh` (`set -eu`) runs `alembic upgrade head` under an advisory lock before uvicorn starts. A live `0490f68` therefore implies the production database reached `045`.

Tests at `0490f68` (synthetic data, no AWS calls)
- 58 passed across `test_aws_marketplace_{events,identity,reconciliation,registration,worker}.py`, `test_platform_api_billing_product.py`, `test_alembic_revision_contract.py` and `test_schema_adoption_contract.py`. They cover:
  - registration validation, disabled-before-AWS and hidden AWS errors
  - the claim-code bind-once flow
  - Stripe and AWS billing-owner guards
  - revocation precedence and stale-license key denial
  - event idempotency, conflicting replays and ack-after-commit
  - worker defaults and the missing-credential path
- Entrypoints run as in the container (`PYTHONPATH=agroai_api`):
  - `process_aws_marketplace_events.py` with defaults exits with "event processing is disabled"; enabled with an invalid queue, it exits with "queue configuration is invalid" before any credential lookup.
  - `reconcile_aws_marketplace.py` with defaults exits with "reconciliation is disabled"; enabled with an invalid seller, it exits with "configuration is invalid" before any AWS call.
- Application defaults: `AWS_MARKETPLACE_ONBOARDING_ENABLED=false`, `AWS_MARKETPLACE_EVENTS_ENABLED=false`, `AWS_MARKETPLACE_REGION=us-east-1`.
- `scripts/scan_repository_secrets.py` passed across 2229 paths.

## Not verified in this pass

These require authenticated access that the verifying session did not have:
- AWS caller identity, the CloudFormation stack `agroai-marketplace-events`, the EventBridge rule and target, the SQS queue and DLQ attributes, and the state of product `prod-rrjrdndw2eptq`, its offers and listing.
- Seller tax, bank and disbursement status.
- Render service environment variables, deploy history and logs (no Render API key).

## Historical facts (not re-verified here)

- Earlier session, 2026-10-05/06: stack `agroai-marketplace-events` (`us-east-1`) was UPDATE_COMPLETE with an EventBridge rule, an encrypted SQS queue and an encrypted DLQ. The product was a draft with no offer, and the listing was not live.
- Reported by the account owner: Render deploy `dep-db2hi3jl550s73ch8b7g` went live, its logs show migrations 043 and 044 applied, and AWS has emailed that the seller profile is approved.

## Remaining gates, in order

1. Read-only verification of AWS state through seller-account workload identity (GitHub OIDC role or an equivalent short-lived role), with no long-lived keys.
2. Configure Render with non-secret settings (`AWS_MARKETPLACE_SELLER_ACCOUNT_ID`, `AWS_MARKETPLACE_PRODUCT_ID`, `AWS_MARKETPLACE_PRODUCT_CODE`, `AWS_MARKETPLACE_QUEUE_URL`) and short-lived worker credentials. Keep both flags `false` until the worker authenticates as the seller account.
3. Prepare the offer using only the approved prices: Developer at $149/month or $1,430/year, and Scale at $749/month or $7,190/year. Stop before publishing or accepting any terms; that is the account owner's decision.
4. Run a limited-visibility purchase and cancellation (account owner), then enable the flags and submit the listing for AWS review (account owner).
