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

All endpoints require the feature flag and derive tenant scope from authenticated API-key/session context. `X-Organization-Id` is only a match-check for authenticated tenants or an explicit non-production demo selector.

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
- `POST /v1/compliance/evidence`
- `GET /v1/compliance/audit-log`
- `POST /v1/compliance/exports`
- `GET /v1/compliance/exports/{export_id}`

## Local test instructions

```bash
cd agroai_api
CALIFORNIA_COMPLIANCE_PACK_ENABLED=true pytest tests/unit/test_compliance_pack.py
```

## Railway deployment checks

1. Set `CALIFORNIA_COMPLIANCE_PACK_ENABLED=true` only for tenants/environments approved for controlled rollout.
2. Run `alembic upgrade head` and verify `002_california_compliance_pack` is applied.
3. Smoke test `GET /v1/health` and `GET /v1/compliance/status` with a tenant header.
4. Confirm logs do not contain direct-filing claims or regulator-endorsement language.

## Cloudflare Pages deployment checks

1. Set an injected config or environment transform so `window.AGROAI_PORTAL_CONFIG.CALIFORNIA_COMPLIANCE_PACK_ENABLED=true` only in the target portal.
2. Confirm the `Compliance` nav item is hidden when the flag is false and visible when true.
3. Run a browser smoke test for export controls and disclaimer visibility.

## Known limitations

- No direct filing into SGMA Portal or GEARS.
- The PDF/XLSX composers return structured placeholders for Phase 1 rather than binary rendered files.
- The workbook field dictionary was unavailable in this repository and should be reconciled before broader rollout.
- The fixture is representative California vineyard data, not customer production data.


## Global kernel v2 update

Production compliance services now use tenant-scoped database repositories. The California fixture remains available only when `COMPLIANCE_DEMO_FIXTURES_ENABLED=true`; otherwise requests require an API key tied to the existing tenant authentication model. CSV, XLSX, JSON, and PDF exports are generated as downloadable evidence packages and persisted in `compliance_exports`.


## Correction pass security update

Production portal JavaScript must not embed tenant API keys. Compliance requests now derive tenant scope from an authenticated API key/session or a future short-lived backend-issued token. The `X-Organization-Id` header is accepted only as a match-check for authenticated tenants or for explicitly enabled non-production demo fixtures.

Export binaries are rendered as real CSV/XLSX/PDF/JSON artifacts. The database stores export metadata and a development-only `database_dev_fallback` may store base64 content for local demos; production should use object storage via server-side credentials.


## Parcel identity

`parcel_identifier` is the generic required parcel identifier for global use. `apn` is retained as a nullable California/U.S. legacy compatibility field. Existing California rows are backfilled from `apn` during migration `003`; future international rows may provide `parcel_identifier` without `apn`.
