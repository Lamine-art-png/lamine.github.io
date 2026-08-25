# Assurance rollout and rollback

## Server-owned release states

`ASSURANCE_RELEASE_STATE` accepts `disabled`, `internal`, `canary`, or `general`. An explicit valid value always wins. Unknown non-empty values fail closed to `disabled`.

AGRO-AI approved Assurance Intelligence V2 for general production release on 2026-08-23. When `ASSURANCE_RELEASE_STATE` is unset, a real production runtime with an immutable deployed build identity now inherits the source-controlled `general` release state. A local process that only claims `APP_ENV=production` remains `disabled`, and staging remains `disabled` when unset.

This keeps an emergency configuration kill switch after GA: setting `ASSURANCE_RELEASE_STATE=disabled` immediately overrides the source-controlled default. `internal` and `canary` can likewise be restored through deployment configuration if a bounded cohort is needed. Internal and canary Organization allowlists come from secure comma-separated deployment configuration. Browser state, query parameters, headers, and customer-controlled metadata cannot select a cohort.

The release gate runs before repository access. Commercial entitlements then separately control:

- `assurance.readiness`;
- `assurance.evidence_mapping`;
- `assurance.review`;
- `assurance.exports`;
- `assurance.agent`.

Free accounts receive readiness preview only. Professional enables readiness, mapping, and exports. Team and higher enable review and agent/task workflows. The backend is authoritative; frontend locks are explanatory UX.

## General-release production contract

General availability does not weaken the Assurance trust boundary. A production release is accepted only when the normal production contract proves the deployed backend has an immutable build SHA, the database is at the repository Alembic head, the durable Queue is configured, object storage is configured and reachable, and production readiness is green. The Enterprise Portal Assurance route must also serve the production Portal shell.

Modern package generation still fails closed when durable object storage is unavailable. Human review remains authoritative. Assurance remains decision support and does not become a legal certification, regulatory approval, automatic filing, external-delivery agent, connector executor, or physical-control system.

## Rollback

The preferred immediate rollback is configuration-only: set `ASSURANCE_RELEASE_STATE=disabled`. This hides Portal Assurance while preserving all data and historical API-key endpoints. The Portal’s route-local recovery keeps the rest of the app operable if the Assurance chunk fails.

If deployment configuration tooling is unavailable, a reviewed source rollback may change the production default back to `disabled` and deploy through the normal immutable release path. Explicit deployment configuration remains authoritative whenever it is available.

Code rollback can leave the additive revision-030 schema in place. A schema downgrade is permitted only when its read-only preflight finds no workspace-owned row without a legacy `tenant_id` and no revision-030 review/audit event. Otherwise it fails before dropping a table, index, or column and identifies the blocking tables and row counts. Migrate or archive the data into a legacy-compatible form, or remove it only through an explicitly approved retention procedure, before retrying. Immutable exports and review/audit history remain subject to customer retention policy.

## Release evidence

The GA verification workflow records the exact deployed backend SHA and the authenticated release-health contract, including schema, Queue, durable object storage, production readiness, and `assurance_release_state=general`, then smokes the production `/assurance` Portal route. A release is not considered complete merely because the source branch was merged.
