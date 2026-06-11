# California Compliance Pack v0.1

## Architecture note

The pack is a feature-flagged extension of the existing AGRO-AI API and portal. Enable it with `CALIFORNIA_COMPLIANCE_PACK_ENABLED=true`. Endpoints live under `/v1/compliance`; the enterprise portal shows a `Compliance` tab only when `window.AGROAI_PORTAL_CONFIG.CALIFORNIA_COMPLIANCE_PACK_ENABLED` is true.

The reusable kernel contains jurisdiction resolution, organization/permissions records, parcel/well/meter registries, an immutable measurement ledger, execution reconciliation, water budgets, evidence metadata, a versioned rule-pack abstraction, readiness checks, and export composition.

## Compliance claims disclaimer

AGRO-AI prepares reporting-readiness evidence only. It does not provide legal advice, certify measurement methods, guarantee compliance, file with SGMA Portal or GEARS, or imply regulator endorsement. Every material value must retain one truth label: `measured`, `reported`, `estimated`, `calculated`, or `AI-inferred`.

## Schema mapping note

The attached `AGRO-AI_SGMA_GEARS_Data_Dictionary.xlsx` was requested as the canonical field reference, but it is not present in this checkout. Phase 1 therefore implements the prompt-provided fields directly and isolates mappings in code and docs for later workbook reconciliation.

### GEARS readiness fields

- reporting year → `compliance_jurisdictions.reporting_year`
- owner details → `compliance_organization_roles.owner`
- reporting agent details and authorization → `compliance_organization_roles.reporting_agent`, `compliance_evidence.artifact_type=agent_authorization`
- well identifier/location/capacity → `compliance_wells`
- monthly groundwater extraction volumes → `compliance_measurements` with `measurement_type=groundwater_extraction`
- place and purpose of use → parcel/well metadata and evidence package fields
- measurement method/calibration evidence → `compliance_meters`, `compliance_evidence`
- missing-data explanation/submission artifact reference → `compliance_evidence`, export `missing_data_flags`

### SGMA GSA readiness fields

- reporting period, basin, subbasin, GSA → `compliance_jurisdictions`
- parcel/well relationships → `compliance_parcels`, `compliance_wells`
- extraction, surface-water, total-use, and water-budget summaries → `compliance_measurements`, `compliance_water_budgets`
- storage-change support, monitoring evidence, data-quality flags, methodology notes, report artifacts → `compliance_evidence` and export methodology.

## Endpoint documentation

All endpoints require the feature flag. Production tenant scope is derived server-side from a verified `X-API-Key`; `X-Organization-Id` is never trusted as authority and requests are rejected when the header conflicts with the authenticated tenant. Non-production fixtures require `COMPLIANCE_DEMO_FIXTURES_ENABLED=true` plus `X-Compliance-Demo-Token`, and the token is pinned to the approved fixture tenant.

- `GET /v1/compliance/status`
- `GET /v1/compliance/jurisdictions`
- `GET /v1/compliance/assets/parcels`
- `GET /v1/compliance/assets/wells`
- `GET /v1/compliance/assets/meters`
- `POST /v1/compliance/measurements`
- `GET /v1/compliance/measurements`
- `GET /v1/compliance/reconciliation`
- `GET /v1/compliance/water-budgets`
- `GET /v1/compliance/readiness?workflow_type=gears_groundwater_extractor_readiness`
- `POST /v1/compliance/readiness/snapshots`
- `POST /v1/compliance/evidence`
- `POST /v1/compliance/exports`
- `GET /v1/compliance/exports/{export_id}`

## Local test instructions

```bash
cd agroai_api
pytest tests/unit/test_compliance_pack.py
```

## Production Deployment Checks

1. Set `CALIFORNIA_COMPLIANCE_PACK_ENABLED=true` only for tenants/environments approved for controlled rollout.
2. Before touching production data, run `python -m py_compile alembic/versions/002_california_compliance_pack.py alembic/versions/003_global_compliance_kernel.py scripts/compliance_migration_preflight.py` and `alembic heads` against the release image.
3. Take a platform-managed PostgreSQL backup or verified database snapshot, or run the migration first against a restored copy of the production database.
4. Run `python scripts/compliance_migration_preflight.py --database-url "$DATABASE_URL"` to confirm the starting revision and schema shape before any migration command.
5. Run `alembic current` to confirm the preflight starting revision, then run `alembic upgrade head` and verify `002_california_compliance_pack` and `003_global_compliance_kernel` are applied.
6. Confirm PostgreSQL no longer retains an unused `compliance_workflow_type` enum after migration 003, while `compliance_truth_label` remains available for migration 002 tables.
7. Smoke test `GET /v1/health` and `GET /v1/compliance/status` with a verified server-side API key or explicitly labeled non-production demo token.
8. Confirm logs do not contain direct-filing claims or regulator-endorsement language.

### Production database migration decision tree

**A. Clean baseline with no compliance tables**

1. Take a platform-managed PostgreSQL backup or verified database snapshot.
2. Run `python scripts/compliance_migration_preflight.py --database-url "$DATABASE_URL"` and confirm `A_clean_baseline_no_compliance_tables`.
3. Run `alembic upgrade head`.
4. Verify `alembic current`, compliance table creation, and a read-only `GET /v1/compliance/status` smoke test.

**B. Database already stamped at 002**

1. Take a platform-managed PostgreSQL backup or verified database snapshot.
2. Run `python scripts/compliance_migration_preflight.py --database-url "$DATABASE_URL"` and confirm revision `002_california_compliance_pack` with `B_migration_002_schema`.
3. Run `alembic upgrade head`.
4. Verify migration 003 additions, including `parcel_identifier` backfill and `compliance_export_metadata`.

**C. Compliance tables exist but Alembic is not stamped at 002**

1. Stop before running production migrations.
2. Restore a production copy in staging.
3. Compare the live schema carefully against the historical migration 002 shape and existing row data.
4. Only after manual verification, use an explicit stamp-and-upgrade procedure in the restored environment first.
5. Never auto-stamp production blindly.

**D. Partial or ambiguous schema**

1. Stop.
2. Do not migrate.
3. Reconcile the schema manually before any stamp or upgrade command.

## Cloudflare Pages deployment checks

1. Set an injected config or environment transform so `window.AGROAI_PORTAL_CONFIG.CALIFORNIA_COMPLIANCE_PACK_ENABLED=true` only in the target portal.
2. Confirm the `Compliance` nav item is hidden when the flag is false and visible when true.
3. Run a browser smoke test for export controls and disclaimer visibility.

## Known limitations

- No direct filing into SGMA Portal or GEARS.
- PDF/XLSX binary export is not implemented; object storage backends are not implemented and fail closed.
- The workbook field dictionary was unavailable in this repository and should be reconciled before broader rollout.
- The fixture is representative California vineyard data, not customer production data.
