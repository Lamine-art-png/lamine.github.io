# Global Compliance Kernel v2 correction pass

## Current repository state

The local checkout now has `origin` configured for `Lamine-art-png/lamine.github.io`, but direct GitHub fetch/push access returned a `CONNECT tunnel failed, response 403` error in this environment. This correction pass was applied to the latest available local branch state and could not verify or update the remote branch from here.

## Security model

Production browser JavaScript must never embed tenant API keys. Compliance API requests must be authorized by one of these server-side patterns:

1. authenticated backend session using `credentials: "include"`;
2. a secure server-side proxy that injects tenant credentials outside the browser; or
3. a short-lived scoped token issued by the backend.

For isolated development and demos only, `COMPLIANCE_DEMO_FIXTURES_ENABLED=true` allows `X-Compliance-Demo-Token` with `COMPLIANCE_DEMO_TOKEN`. This token is explicitly non-production and only seeds representative fixture data. `X-Organization-Id` is accepted only for this demo/testing path or as a match-check against an authenticated tenant; it is never trusted as authority.

## Tenant isolation

- With `X-API-Key`, the tenant is derived from `APIKeyService.verify_api_key`.
- If `X-Organization-Id` is supplied with an authenticated API key, it must match the authenticated tenant or the request is rejected with 403.
- Without an API key, production mode rejects requests with 401.
- Fixture data is loaded only through `COMPLIANCE_DEMO_FIXTURES_ENABLED=true` and a valid `X-Compliance-Demo-Token`.

## Export storage architecture

Rendered CSV, XLSX, JSON, and PDF files are real export artifacts. The relational database stores export metadata:

- tenant ID;
- workflow type;
- readiness status/snapshot metadata;
- created-at timestamp;
- filename and MIME type;
- storage backend;
- storage reference;
- SHA-256 checksum;
- byte length.

`database_dev_fallback` stores base64 content in `compliance_exports.content_base64` only when `COMPLIANCE_ALLOW_DATABASE_DEV_FALLBACK=true` for local development and controlled demos. Production should keep that setting false and configure a real object-storage backend before enabling exports. If object storage is not implemented, export creation fails closed instead of returning fake storage references. Direct browser-stored API keys are not part of the production design.

## Jurisdiction packs

- California remains the first controlled/enabled reporting-readiness pack for SGMA GSA annual-readiness and GEARS groundwater-extractor readiness, with legal-review status `internal_alpha_pending_external_validation` rather than legal approval.
- Arizona is the first substantive non-California alpha pack and remains disabled pending legal review.
- Other U.S. and international packs are disabled research-only skeletons with legal-review gates.

Each pack retains pack ID, version, country code, region, authority, workflow types, legal-review status, enabled status, required fields, conditional fields, validation rules, deadlines, warning thresholds, export schema, disclaimer, source references, and last-reviewed date.

## Deployment order

1. Deploy migration-safe code with `CALIFORNIA_COMPLIANCE_PACK_ENABLED=false`.
2. Run `alembic upgrade head`.
3. Verify compliance tables, workflow columns, and `compliance_exports` metadata columns.
4. Enable `CALIFORNIA_COMPLIANCE_PACK_ENABLED` only after schema verification.

Application startup intentionally excludes `compliance_*` tables from production `Base.metadata.create_all()`; Alembic owns the compliance schema. Isolated tests may still call `Base.metadata.create_all()` directly.

## Migration safety

`003_global_compliance_kernel` is intended to run after `002_california_compliance_pack` and is non-destructive:

- adds nullable/global columns or columns with safe server defaults;
- does not rename or drop PR 52 tables/columns;
- does not recreate existing California tables;
- creates `compliance_exports` as a new table;
- uses SQLAlchemy inspection guards for additive columns and indexes;
- leaves additive rollout columns in place on downgrade to avoid accidental production data loss.

## Canonical reference blocker

The requested files were not present under `/workspace` during this correction pass:

1. `AGRO-AI_Global_Compliance_Kernel_Codex_Prompt_V2.md`
2. `AGRO-AI_SGMA_GEARS_Data_Dictionary.xlsx`
3. `AGRO-AI_Global_Water_Compliance_Atlas.xlsx`

Workbook-driven California reconciliation remains pending until those files are available in the repository or task attachment mount.

## Non-claims disclaimer

AGRO-AI prepares reporting-readiness evidence only. It does not provide legal advice, certify measurement methods, guarantee compliance, file reports with regulators, or imply regulator endorsement.

## Browser authentication boundary for this PR

This repository currently has API-key verification and a demo JWT helper, but no production browser-session or short-lived compliance-token dependency that derives a tenant server-side for the V2 browser app. Until that backend session/proxy is implemented, the V2 Compliance browser client intentionally fails closed unless `VITE_NON_PRODUCTION_COMPLIANCE_DEMO_TOKEN` is configured for an explicitly labeled non-production demo. Production compliance API access remains server-to-server through verified tenant API keys; tenant API keys must not be embedded in browser JavaScript or Cloudflare Pages configuration.

## Next-sprint global abstraction registry design

This PR is a groundwater-first, global-ready compliance kernel foundation. The next sprint should add a jurisdiction-neutral abstraction registry for water assets and rights, including:

- surface-water abstraction points;
- diversion points;
- intake points;
- canal deliveries;
- licences;
- concessions;
- water rights;
- groundwater wells;
- meters;
- telemetry sources;
- authority-specific asset identifiers.

The registry should map local authority identifiers to AGRO-AI canonical assets without implying legal certification, regulator endorsement, or direct filing capability.


## Parcel identity

`parcel_identifier` is the generic required parcel identifier for global use. `apn` is retained as a nullable California/U.S. legacy compatibility field. Existing California rows are backfilled from `apn` during migration `003`; future international rows may provide `parcel_identifier` without `apn`.
