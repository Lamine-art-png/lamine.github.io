# Terris Module Registry

The typed registry lives in `apps/velia-mobile/js/domain/moduleRegistry.js`.

## Modules

- Terris Water: `active`, enabled by default, route `water`.
- Terris Nutrients: `beta`, enabled by default, route `nutrients`.
- Terris Energy: `beta`, enabled by default, route `energy`.
- Terris Ops: `beta`, enabled by default, route `tasks`.
- Terris Proof: `beta`, enabled by default, route `ledger` and Proof surface.
- Terris Protect: `preview`, disabled by default, roadmap only.
- Terris Risk API: `reserved`, disabled by default, roadmap only.

## Feature Flags

- `TERRIS_WATER_ENABLED=true`
- `TERRIS_NUTRIENTS_ENABLED=true`
- `TERRIS_ENERGY_ENABLED=true`
- `TERRIS_OPS_ENABLED=true`
- `TERRIS_PROOF_ENABLED=true`
- `TERRIS_PROTECT_ENABLED=false`
- `TERRIS_RISK_API_ENABLED=false`

Legacy `VELIA_*` backend flags are fallback aliases only.

## Navigation Rules

Enabled modules have usable surfaces. Disabled preview or reserved modules appear only as roadmap surfaces and are not clickable broken workflows.
