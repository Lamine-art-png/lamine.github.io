# Global Compliance Kernel v2 correction pass

## Current repository state

The local checkout does not expose a configured Git remote and direct GitHub access returned a 403 tunnel response, so this correction pass could not fetch the latest remote `main`. It was applied to the latest available local branch state. The expected `apps/agroai-command-center-v2/` directory from PR 53 was also absent locally, so this patch adds the native Compliance page files in that path without modifying unknown PR 53 files.

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

`database_dev_fallback` stores base64 content in `compliance_exports.content_base64` only for local development and controlled demos. Production should set `COMPLIANCE_EXPORT_STORAGE_BACKEND` to an object-storage implementation and store rendered files in S3/GCS/R2 or equivalent using server-side credentials. Direct browser-stored API keys are not part of the production design.

## Jurisdiction packs

- California remains the first approved/enabled pack for SGMA GSA annual-readiness and GEARS groundwater-extractor readiness.
- Arizona is the first substantive non-California alpha pack and remains disabled pending legal review.
- Other U.S. and international packs are disabled research-only skeletons with legal-review gates.

Each pack retains pack ID, version, country code, region, authority, workflow types, legal-review status, enabled status, required fields, conditional fields, validation rules, deadlines, warning thresholds, export schema, disclaimer, source references, and last-reviewed date.

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
