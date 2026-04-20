# Portal Live API Route Audit

Routes targeted for portal wiring (matching deployed API contract paths):

## Controller environments
- `GET /v1/controllers/environments`

## Farms & zones
- `GET /v1/wiseconn/farms`
- `GET /v1/wiseconn/farms/{farm_id}/zones`
- `GET /v1/talgil/farms`
- `GET /v1/talgil/farms/{farm_id}/zones`

## Runtime auth/status
- `GET /v1/wiseconn/auth`
- `GET /v1/talgil/auth`
- `GET /v1/talgil/targets`

## WiseConn irrigations
- `GET /v1/wiseconn/zones/{zone_id}/irrigations`

## Decisioning water-state
- `GET /v1/decisioning/blocks/{block_id}/water-state`
- `GET /v1/decisioning/blocks/{block_id}/water-state/history`

## Decisioning / recommendation-related operational flows
- `GET /v1/execution/blocks/{block_id}/decisions`
- `GET /v1/execution/blocks/{block_id}/verifications`

## Reports
- `GET /v1/reports/roi`

## Notes
- Portal reads are wired to the above routes only.
- `GET /v1/controllers/environments` is source-aware and now evaluates Talgil status from real `/v1/talgil` runtime reads.
- UI marks Reports as “not yet wired” when `/v1/reports/roi` is not exposed by the live deployment (e.g., 404).
