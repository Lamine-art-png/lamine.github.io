# Terris Module Registry

The module registry is implemented in `apps/velia-mobile/js/domain/moduleRegistry.js`.

## Defaults

- `TERRIS_WATER_ENABLED=true`
- `TERRIS_NUTRIENTS_ENABLED=false`
- `TERRIS_ENERGY_ENABLED=false`
- `TERRIS_OPS_ENABLED=false`
- `TERRIS_PROOF_ENABLED=false`
- `TERRIS_PROTECT_ENABLED=false`
- `TERRIS_RISK_API_ENABLED=false`

Legacy `VELIA_*` aliases remain fallback-only compatibility names.

## Demo Mode

Beta modules may be displayed as representative demo surfaces in demo mode. They are labeled as representative and must not imply live integrations.

Protect and Risk API remain disabled in demo mode unless explicitly enabled for controlled development.
