# Terris Rename Compatibility

The active product brand is Terris. User-visible active UI strings now use Terris.

## Renamed Surfaces

- Mobile app name, manifest, HTML title, onboarding, assistant labels, and module surfaces.
- Backend service ID and startup message.
- Package names in active mobile and backend `package.json`.
- Backend model schema name defaults.
- Knowledge guidance references.
- Customer portal model label and storage prefix.

## Retained Aliases

Persisted browser storage:
- canonical mobile prefix: `terris-mobile:`
- legacy mobile prefix: `velia-mobile:` read through and migrated forward without deleting the old value
- canonical portal prefix: `terris:`
- legacy portal prefix: `velia:` read through and migrated forward without deleting the old value

Client API base URL:
- canonical key: `terrisApiBaseUrl`
- legacy key: `veliaApiBaseUrl`

Environment variables:
- canonical `TERRIS_*` memory/cache/module flags take precedence
- legacy `VELIA_*` names remain fallback aliases only

## Deprecated Legacy Names

The old Velia product name is deprecated. Legacy names remain only where changing them would break local paths, persisted data, environment configuration, or explicit compatibility tests.

## Remaining Allowed Matches

- `apps/velia-mobile` and `apps/velia-ai-api`: retained compatibility directory paths.
- `velia-mobile:` and `velia:`: legacy storage prefixes read during forward migration.
- `veliaApiBaseUrl`: legacy client configuration fallback.
- `VELIA_*`: legacy backend environment variable fallback aliases.
- test strings containing Velia: explicit compatibility coverage.
- `velia-weather-*` temporary test filename: harmless test cache name, not product UI or contract.

No active product UI should display Velia.
