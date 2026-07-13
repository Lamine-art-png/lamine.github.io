# Platform API Operations Runbook

## Required Production Configuration

- `PLATFORM_API_ENABLED=false` for initial schema/code deploy.
- `PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED=false` until internal testing.
- `PLATFORM_API_KEY_PEPPER` configured outside the database.
- `PLATFORM_API_RATE_LIMIT_BACKEND=redis`.
- `PLATFORM_API_REDIS_URL` or existing `REDIS_URL`.
- `PLATFORM_API_REDIS_MAX_RETRIES=1` (idempotent transient retry; increase only with load evidence).
- `PLATFORM_API_REDIS_CONNECT_TIMEOUT_SECONDS=2` and `PLATFORM_API_REDIS_SOCKET_TIMEOUT_SECONDS=2`.
- Test policy: `PLATFORM_API_TEST_BURST_LIMIT=60`, `PLATFORM_API_TEST_SUSTAINED_LIMIT=600`.
- Live policy: `PLATFORM_API_LIVE_BURST_LIMIT=600`, `PLATFORM_API_LIVE_SUSTAINED_LIMIT=6000`.
- `CONNECTOR_CREDENTIAL_KEYS_JSON` containing the active 32-byte AES key and `CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION`.
- `PLATFORM_API_WEBHOOK_DELIVERY_ENABLED=false` until delivery workers are reviewed.
- `EARTHDAILY_ADAPTER_ENABLED=false`.
- `VALLEY_IRRIGATION_ADAPTER_ENABLED=false`.
- `VALLEY_IRRIGATION_WRITE_CAPABILITY_ENABLED=false`.

## Readiness Checks

- Portal readiness remains `/v1/readiness`.
- Platform API readiness is `/v1/platform/health`.
- When Platform API is enabled, `/v1/platform/health` pings the configured Redis backend and reports `not_ready` when Redis is absent or unavailable.
- Optional provider contract readiness must not fail Portal readiness.

## Incident Actions

1. Disable `PLATFORM_API_ENABLED`.
2. Revoke impacted Platform API keys.
3. Disable affected API projects.
4. Disable webhook endpoints if delivery is involved.
5. Preserve request IDs and usage events for investigation.
6. Use existing rollback workflow only with exact-SHA evidence.
