# Field Intelligence integration conflict report

- integration branch head: `6323e2464ae333f7033f072b540aa32caa73328f`
- current main head: `9e7a7d1e8a1482318b25d2734ccd55899524e451`
- feature head: `02f5a424ae09aefa9c0baaa23771e3c329dd34eb`
- merge exit: `1`

## Conflicting files
```
.github/workflows/ci.yml
.github/workflows/hardening-backend-reusable.yml
agroai_api/app/db/schema_contract.py
agroai_api/tests/unit/test_alembic_revision_contract.py
agroai_api/tests/unit/test_schema_adoption_contract.py
docs/DEPLOYMENT_TRUTH_MAP.md
docs/platform-api-operations-runbook.md
```

## Conflict excerpts

### `.github/workflows/ci.yml`
```diff
<<<<<<< HEAD
          test "$(alembic heads)" = "026_platform_api_operations (head)"
=======
          test "$(alembic heads)" = "024_field_intelligence_launch (head)"
>>>>>>> origin/feature/field-intelligence-launch
```

### `.github/workflows/hardening-backend-reusable.yml`
```diff
<<<<<<< HEAD
          test "$(alembic heads)" = "026_platform_api_operations (head)"
=======
          test "$(alembic heads)" = "024_field_intelligence_launch (head)"
>>>>>>> origin/feature/field-intelligence-launch
```

### `agroai_api/app/db/schema_contract.py`
```diff
<<<<<<< HEAD
HEAD_ALEMBIC_REVISION = "026_platform_api_operations"
=======
HEAD_ALEMBIC_REVISION = "024_field_intelligence_launch"
>>>>>>> origin/feature/field-intelligence-launch
<<<<<<< HEAD
    "platform_api_applications": {"id", "organization_id", "applicant_user_id", "application_type", "status"},
    "platform_program_enrollments": {"id", "organization_id", "program", "status", "allowed_environments_json"},
    "platform_live_access_requests": {"id", "organization_id", "requested_by_user_id", "status"},
    "platform_partner_dossiers": {"id", "organization_id", "provider_id", "production_readiness"},
    "platform_product_audit_events": {"id", "organization_id", "event_type", "subject_type", "subject_id"},
    "platform_terms_documents": {"id", "document_type", "version", "status"},
    "platform_terms_acceptances": {"id", "organization_id", "user_id", "document_id", "accepted_at"},
    "platform_api_plans": {"id", "catalog_version", "plan_identifier", "active", "included_credits"},
    "platform_api_operation_costs": {"id", "catalog_version", "operation_id", "environment", "credits"},
    "platform_api_subscriptions": {"id", "organization_id", "plan_id", "status", "status_slot"},
    "platform_checkout_idempotency": {
        "id",
        "organization_id",
        "operation",
        "client_key",
        "request_hash",
        "status",
    },
    "platform_credit_reservations": {"id", "organization_id", "api_project_id", "logical_operation_id", "state"},
    "platform_stripe_meter_outbox": {"id", "organization_id", "usage_event_id", "meter_event_identifier", "status"},
    "platform_stripe_events": {"id", "stripe_event_id", "event_type", "status"},
    "platform_request_logs": {
        "id",
        "organization_id",
        "api_project_id",
        "request_id",
        "client_correlation_id",
        "operation_id",
    },
    "platform_notifications": {"id", "organization_id", "notification_type", "dedupe_key", "status"},
    "platform_sandbox_states": {"id", "organization_id", "api_project_id", "fixture_version", "reset_counter"},
    "platform_support_requests": {"id", "organization_id", "category", "severity", "status"},
    "platform_support_messages": {"id", "support_request_id", "visibility", "body"},
    "platform_status_components": {"id", "component_key", "status", "public"},
    "platform_status_incidents": {"id", "status", "severity", "public_summary"},
    "platform_status_incident_updates": {"id", "incident_id", "status", "public_message"},
    "platform_abuse_events": {"id", "organization_id", "signal_type", "status"},
=======
    "field_runtime_flags": {"key", "value_json", "updated_at"},
    "field_worker_heartbeats": {"worker_id", "git_sha", "last_heartbeat_at"},
>>>>>>> origin/feature/field-intelligence-launch
```

### `agroai_api/tests/unit/test_alembic_revision_contract.py`
```diff
<<<<<<< HEAD
        "024_platform_api_programs": "023_field_intelligence",
        "025_platform_api_commerce": "024_platform_api_programs",
        "026_platform_api_operations": "025_platform_api_commerce",
=======
        "024_field_intelligence_launch": "023_field_intelligence",
>>>>>>> origin/feature/field-intelligence-launch
```

### `agroai_api/tests/unit/test_schema_adoption_contract.py`
```diff
<<<<<<< HEAD
def test_head_contract_covers_security_queue_provenance_access_appeals_and_platform_api():
    assert HEAD_ALEMBIC_REVISION == "026_platform_api_operations"
=======
def test_head_contract_covers_security_queue_provenance_access_appeals_and_field_intelligence():
    assert HEAD_ALEMBIC_REVISION == "024_field_intelligence_launch"
>>>>>>> origin/feature/field-intelligence-launch
```

### `docs/DEPLOYMENT_TRUTH_MAP.md`
```diff
<<<<<<< HEAD
## J. Platform API product surfaces (disabled)

The authoritative public marketing source is the root Cloudflare Pages project.
`/platform-api` and `/developers` are static assets guarded by Pages Functions
using server-side `PLATFORM_API_MARKETING_ENABLED` and
`PLATFORM_API_PUBLIC_DOCS_ENABLED`. Both default false, return 404 with
`noindex` while disabled, and are not present in navigation or sitemap.

The customer developer console remains inside `figma-enterprise-v4` at
`/developers/api`. Its navigation is granted only after the backend confirms
the developer-control-plane flag, approved organization, active owner/admin
membership, and active enrollment. Platform administrators use the separate
`/admin/platform-api` route.

API billing extends the existing backend but does not reinterpret Enterprise
Portal subscriptions. Stripe configuration is server-only and all API billing,
Checkout, meter export, pricing, Tax, support, status, applications, partner,
self-service, and live-access flags default false.
=======
## G. Field Intelligence Staging (isolated)

An entirely separate topology for pre-production Field Intelligence review.
Deployed ONLY by the manually gated `Field Intelligence Staging` workflow
(`workflow_dispatch`, protected GitHub environment
`field-intelligence-staging`); it never runs on push and never touches any
production surface. `api-preview.agroai-pilot.com` and
`agroai-api-preview.onrender.com` are the PRODUCTION upstream (the public
edge routes to them) and are refused as staging targets.

- Portal: Cloudflare Pages project `agroai-portal-staging`, branch
  `field-intelligence-staging`, built with
  `VITE_DEPLOYMENT_ENVIRONMENT=staging` (visible banner + exact build SHA,
  noindex, staging-namespaced service-worker cache) and
  `VITE_API_BASE_URL=<staging API URL>` only.
- API: dedicated staging service (`FIELD_STAGING_API_URL`), deployed from an
  exact SHA via `FIELD_STAGING_DEPLOY_HOOK`; `/v1/health` reports
  `build_sha` for alignment.
- Database: dedicated staging PostgreSQL (`FIELD_STAGING_DATABASE_URL`);
  migration chain and 024→022→024 rollback proven on a disposable
  `fi_staging_rollback_proof` database per run.
- Worker: staging worker service or the staging API's in-process worker;
  SHA-bearing heartbeats in `field_worker_heartbeats` are required evidence.
- Objects: dedicated staging R2 bucket (name contains `staging`), prefix
  `staging/field-intelligence/`, staging-scoped credentials only.
- Release state: `internal` (general refused; canary needs
  `CONFIRM_STAGING_CANARY`).
- Contracts: `agroai_api/scripts/field_intelligence_staging_contract.py` and
  `tests/unit/test_field_intelligence_staging_contract.py` enforce all
  refusals; runbook: `docs/field-intelligence-staging-runbook.md`.
- Future DNS (manual only): `api-staging.agroai-pilot.com` and a staging
  portal hostname.
>>>>>>> origin/feature/field-intelligence-launch
```

### `docs/platform-api-operations-runbook.md`
```diff
<<<<<<< HEAD
- The required linear Alembic tail is `019_account_verification` → `020_platform_api_private_beta` → `021_platform_api_hardening` → `022_account_access_appeals` → `023_field_intelligence` → `024_platform_api_programs` → `025_platform_api_commerce` → `026_platform_api_operations`; `alembic heads` must return only `026_platform_api_operations`.
=======
- The required linear Alembic tail is `019_account_verification` → `020_platform_api_private_beta` → `021_platform_api_hardening` → `022_account_access_appeals` → `023_field_intelligence` → `024_field_intelligence_launch`; `alembic heads` must return only `024_field_intelligence_launch`.
>>>>>>> origin/feature/field-intelligence-launch
```
