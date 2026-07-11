# AGRO-AI Platform API Architecture

Status: Private Enterprise Partner Beta foundation.

The Platform API is an additive control plane inside `agroai_api/`. It does not replace Portal JWT auth, billing, Stripe, existing connectors, uploads, Queue workers, or object storage.

## Boundaries

- Portal routes keep `AuthContext`.
- Partner routes use `PlatformPrincipal` from scoped Platform API keys.
- Internal Queue routes keep queue bearer-token auth.
- Platform-admin routes keep server-side email allowlists.
- New partner namespace: `/v1/platform/...`.

## New Backend Components

- `ApiProject`: organization-owned test/live integration environment.
- `ApiServiceAccount`: project-owned machine identity.
- `PlatformApiKey`: scoped one-time plaintext key with `agro_test_` or `agro_live_` prefix.
- `PlatformApiUsageEvent`: durable request and operation usage events.
- `PlatformIdempotencyRecord`: scoped idempotency records.
- `ProviderExternalIdentityMap`: provider-to-canonical identity mapping.
- `ProviderCapabilityRecord`: adapter-derived capability status.
- `PlatformWebhookEndpoint`, `PlatformWebhookEvent`, `PlatformWebhookDeliveryAttempt`.
- `ActionSafetyConfiguration`: disabled-by-default physical action kill-switch scope.

## Authentication

Platform API keys are hashed with HMAC-SHA256 and a server-side pepper. In production, `PLATFORM_API_KEY_PEPPER` is required. Verification is read-oriented and does not commit usage metadata.

## Rate Limiting

`PLATFORM_API_RATE_LIMIT_BACKEND=redis` is the production backend. The memory backend is accepted only outside production and fails closed in production.

## Providers

Provider adapters are real implementation objects in `app/provider_adapters`. EarthDaily and Valley are integration-readiness adapters only and return `awaiting_partner_contract`.

## Physical Actions

`/v1/platform/actions/execute` is implemented as a deterministic safety denial. Valley write capability remains disabled.
