# Assurance rollout and rollback

## Server-owned release states

`ASSURANCE_RELEASE_STATE` accepts `disabled`, `internal`, `canary`, or `general`. An empty value is `general` only in development/test and fails closed to `disabled` in production/staging. Internal and canary Organization allowlists come from secure comma-separated deployment configuration. Browser state, query parameters, headers, and customer-controlled metadata cannot select a cohort.

The release gate runs before repository access. Commercial entitlements then separately control:

- `assurance.readiness`;
- `assurance.evidence_mapping`;
- `assurance.review`;
- `assurance.exports`;
- `assurance.agent`.

Free accounts receive readiness preview only. Professional enables readiness, mapping, and exports. Team and higher enable review and agent/task workflows. The backend is authoritative; frontend locks are explanatory UX.

## Recommended progression

1. Apply migration `030_assurance_intelligence_v2` with release state `disabled`.
2. Verify schema contract, historical Assurance smoke tests, and portal route isolation.
3. Set `internal` and validate one server-configured Organization against real canonical evidence.
4. Set `canary` for selected Organizations; monitor 404/402/422/5xx rates, package generation latency, and review/task audit rows.
5. Set `general` only after backend and `figma-enterprise-v4` SHAs are deployed together and canary results are accepted.

## Rollback

The immediate rollback is configuration-only: set `ASSURANCE_RELEASE_STATE=disabled`. This hides Portal Assurance while preserving all data and historical API-key endpoints. The Portal’s route-local recovery keeps the rest of the app operable if the Assurance chunk fails.

Code rollback is safe because the migration is additive. Do not downgrade while Portal-era rows exist unless their retention has been planned: the downgrade intentionally refuses to make historical `tenant_id` non-null when null Portal rows exist. Immutable exports and review/audit history should be retained according to customer policy.

## No deployment in this change

This branch changes code, migrations, tests, and documentation only. Production deployment and release-state changes require the normal reviewed release process.
