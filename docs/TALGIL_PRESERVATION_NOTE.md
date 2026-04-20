# Talgil Runtime Note (FastAPI)

## Current state in this branch

- Talgil worker-era integration artifacts remain preserved under `agroai-cloudflare-worker/api-native/`.
- FastAPI now includes real Talgil read-path runtime routes under `/v1/talgil` using the same upstream endpoints family (`/mytargets`, `/targets/{id}/`).
- Controller environment truth (`GET /v1/controllers/environments`) is source-aware for both WiseConn and Talgil:
  - Talgil is `integration_ready` when `TALGIL_API_KEY` is not configured.
  - Talgil is `configured` when key exists but auth/read fails.
  - Talgil is `live` only when runtime auth/read succeeds.

## What this does not claim

- No fabricated Talgil telemetry, recommendations, verification events, or reports.
- No Talgil write path exposure from this FastAPI deployment.
- No DNS/networking/secrets-plane changes.

## Remaining work for parity

1. Persist Talgil reads into AGRO-AI database tables for decisioning/verification/reporting parity.
2. Add source-aware ingestion + scheduling orchestration equivalent to WiseConn sync service.
3. Add historical log/event/water-consumption endpoints only when backed by persisted runtime implementation.
