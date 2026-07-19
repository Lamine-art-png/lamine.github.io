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
- `PlatformWebhookEndpoint`, `PlatformWebhookEvent`, `PlatformWebhookOutbox`, `PlatformWebhookDeliveryAttempt`, and `PlatformWebhookAuditEvent`.
- `ActionSafetyConfiguration`: disabled-by-default physical action kill-switch scope.

## Authentication

Platform API keys are hashed with HMAC-SHA256 and a server-side pepper. In production, `PLATFORM_API_KEY_PEPPER` is required. Verification is read-oriented and does not commit usage metadata.

CIDR restrictions are enforced only from an authenticated Cloudflare-to-Render client-IP assertion. The edge removes caller-supplied forwarding headers, copies Cloudflare's connection address into a dedicated header, and authenticates the hop with `EDGE_ORIGIN_AUTH_TOKEN` / `PLATFORM_API_EDGE_AUTH_SECRET`. CIDR-bound keys fail closed if that context is absent or invalid.

## Rate Limiting

`PLATFORM_API_RATE_LIMIT_BACKEND=redis` is the production backend. The limiter uses atomic Redis counters across organization, project, and API-key dimensions with burst and sustained windows. Weighted route costs are applied by the route handler. Test and live environments have separate Redis keys and policies. The memory backend is accepted only outside production and fails closed in production. Existing Portal traffic is not routed through this limiter in this phase.

## Credential Vault

The Platform API reuses the existing connector AES-256-GCM credential vault through a compatibility adapter. Retrieval is restricted to authorized provider jobs with a Platform API principal, active service account, `connectors:sync` scope, matching organization, matching project, matching provider, matching secret type metadata, and compatible workspace. Metadata inspection excludes ciphertext and nonce.

Webhook signing secrets use a separate versioned AES-256-GCM keyring. Ciphertext associated data binds organization, API project, endpoint, and key version. The plaintext is returned once at creation or rotation; authorized delivery workers retrieve only the selected endpoint secret and emit an audit event. The durable transactional webhook outbox is queue-backed but performs no delivery while `PLATFORM_API_WEBHOOK_DELIVERY_ENABLED=false`.

## Providers

Provider adapters are real implementation objects in `app/provider_adapters`. EarthDaily and Valley are integration-readiness adapters only and return `awaiting_partner_contract`.

## Physical Actions

`/v1/platform/actions/execute` is implemented as a deterministic safety denial. Valley write capability remains disabled.
