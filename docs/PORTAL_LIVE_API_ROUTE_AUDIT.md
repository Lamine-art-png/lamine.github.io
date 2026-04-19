# Portal Live API Route Audit

Routes targeted for portal wiring (matching deployed API contract paths):

## Farms & zones
- `GET /v1/wiseconn/farms`
- `GET /v1/wiseconn/farms/{farm_id}/zones`

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
- UI marks Reports as “not yet wired” when `/v1/reports/roi` is not exposed by the live deployment (e.g., 404).
