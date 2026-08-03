# Terris Rename Compatibility

User-facing product copy is Terris. Compatibility paths and aliases remain where current deployments and persisted users depend on them.

## Retained Physical Names

- `apps/velia-mobile`
- `apps/velia-ai-api`
- package names that existing scripts reference
- legacy localStorage prefixes used for migration
- legacy `VELIA_*` backend environment aliases

## Storage Migration

Mobile reads `terris-mobile:*` first, then migrates `velia-mobile:*` when needed. Customer portal storage reads `terris:*` first, then migrates `velia:*`.

Hydration merges stored state with current defaults so older users gain Terris arrays without losing current main fields such as alerts, recommendation history, remote decisions, weather cache, farm units, water source, data source mode, and verification status.
