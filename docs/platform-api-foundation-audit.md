# AGRO-AI Platform API Foundation Audit

Branch: `feat/platform-api-private-beta`  
Base inspected: `origin/main` at `420c55f0` (`Add branded post-signup founder follow-up (#222)`)  
Audit date: 2026-07-10

## Scope

This audit covers the production AGRO-AI monorepo surfaces that must be preserved while adding the private-beta Platform API:

- Backend: `agroai_api/`
- Enterprise Portal: `figma-enterprise-v4/`
- Cloudflare edge gateway: `cloudflare/edge-gateway/`
- Deployment topology: `docs/DEPLOYMENT_TRUTH_MAP.md`

Terris is out of scope and must not be modified.

## Open PR And Concurrent Work Review

Open PRs were inspected with the GitHub connector because the local `gh` CLI is unavailable. Concurrent work touching nearby surfaces includes:

- PR #204: edge/i18n marker fallback.
- PRs #178/#180/#181/#182: monetization packaging, upload metering, connector tier UI, pricing/paywall behavior.
- PRs #169/#171/#172/#174 and related proof branches: production i18n/edge proof work.
- PR #134: Worker custom domain routing.
- PR #57/#54: older compliance kernel work.
- PR #63: Terris foundation work, explicitly out of scope.
- PR #3: older Talgil Cloudflare Worker connector.

Compatibility response:

- Avoid unrelated edits to i18n runtime, pricing, paywalls, billing, Stripe, and Terris files.
- Do not route existing Portal connector traffic through new Platform API adapters in this first branch.
- Additive backend routes should use an explicit `/v1/platform/...` namespace.

## Existing API Entry Points

Current production backend route registration is centralized in `agroai_api/app/main.py`.

Public and Portal-facing routes include:

- `/health`, `/v1/health`, `/v1/readiness`
- `/v1/auth/*`
- `/v1/billing/*`
- `/v1/preferences/*`
- `/v1/product-shell/*`
- `/v1/orgs/*`, `/v1/workspaces/*`, and SaaS Portal routes from `saas.py`
- `/v1/assurance/*`
- `/v1/wiseconn/*`
- `/v1/talgil/*`
- `/v1/decisioning/*`
- `/v1/execution-assurance/*`
- `/v1/forecast/*`
- `/v1/intelligence/*`
- `/v1/brain/*`
- `/v1/chat-artifacts/*`
- `/v1/workbench/*`
- `/v1/compliance/*`
- `/v1/controllers/*`
- `/v1/ai*`
- `/v1/agents/*`
- `/v1/platform-intelligence/*`
- `/v1/connectors/*`
- `/v1/evidence/*`
- `/v1/operator-cockpit/*`
- `/v1/field-operations/*`

Internal routes exist under `/v1/internal/...`, including Cloudflare Queue and release-contract endpoints from `cloudflare_queue.py`. These use independent queue bearer-token authentication and must remain separate from customer API keys.

Current gap: route classification is implicit. There is no machine-readable manifest that distinguishes Portal, Platform API, internal, platform-admin, and public metadata surfaces.

## Existing Authentication Mechanisms

Current mechanisms:

- Portal JWT: `app/api/deps.py` uses `get_current_user`, `get_auth_context`, membership lookup, email-verification checks, and credential freshness checks.
- Legacy tenant JWT claims: `app/core/security.py` reads `tenant_id` or `org_id` from token claims. `get_current_tenant_id` still has a demo unauthenticated fallback.
- Legacy tenant API keys: `app/services/api_key_service.py` verifies `APIKey` rows bound to `Tenant`.
- Fixed demo API key: `verify_demo_api_key` uses `DEMO_API_KEY`.
- Internal Queue bearer token: `cloudflare_queue.py` validates `CLOUDFLARE_QUEUE_CONSUMER_TOKEN` and optional previous token.
- Platform administrator allowlist: `require_platform_admin` checks verified user email against `PLATFORM_ADMIN_EMAILS`.
- Stripe webhook signature: `billing.py` uses Stripe webhook verification.

Current gap: there is no canonical principal abstraction for Platform API authorization. Browser-provided or JWT-claimed organization/workspace values must not be trusted for Platform API routes.

## Existing Organization And Tenant Models

Current production Portal boundary:

- `Organization`, `Workspace`, `OrganizationMembership`, `User`, billing, entitlements, quotas, and Portal usage records live in `app/models/saas.py`.
- Existing connector-operational tables use `tenant_id` column names but foreign-key to `organizations.id` in several places, including `ConnectorConnection`, `DataSource`, `IngestionJob`, `EvidenceRecord`, and `ConnectorCredential`.

Legacy boundary:

- `Tenant` remains in `app/models/tenant.py`.
- Legacy `APIKey` and `UsageMetering` still foreign-key to `tenants.id`.

Risk: legacy `Tenant` IDs and production `Organization` IDs must not be silently treated as interchangeable. New Platform API models should bind to `organizations.id` while documenting a future compatibility migration for legacy tenant keys.

## Current API-Key Lifecycle

Current legacy service:

- `APIKeyService.generate_key()` creates `agro_...` keys.
- `APIKeyService.create_api_key()` stores SHA-256 hash, prefix, role, field restrictions, active flag, expiration, and audit event.
- `APIKeyService.verify_api_key()` hashes input, looks up active rows, checks expiration, updates `last_used_at`, increments `usage_count`, and commits.
- `APIKeyService.rotate_api_key()` revokes the old key immediately and creates a replacement.

Gaps:

- Keys are tenant-scoped, not organization/project/service-account scoped.
- No test/live prefix distinction.
- No scoped Platform API permissions.
- No rotation overlap window.
- No CIDR, provider, resource, or workspace restriction model.
- Hot path writes on every successful verification.

## Current Portal JWT Lifecycle

Portal lifecycle:

- Register creates user, organization, membership, workspace, and verification token.
- Login is blocked until email verification.
- JWT `sub` is the user ID.
- `get_current_user` verifies JWT signature and credential freshness against `credentials_changed_at`.
- `get_auth_context` enforces email verification and loads the first organization membership.
- `require_org_membership` and `require_workspace_access` verify database membership.

Protected behavior:

- Existing JWT shape, login response, `/v1/auth/me`, email verification, recovery, sessions, and membership behavior must remain unchanged in this branch.

## Current Connector Flow

Connector routes:

- Catalog/setup CRUD: `app/api/v1/connectors.py`
- Secure launch: `connector_launch_secure.py`
- OAuth secure completion: `connector_oauth_secure.py`
- Unified V3 provider flow: `connector_unified_v3.py`
- Provider sync: `connector_provider_sync.py`
- Stream upload: `connector_stream_api.py` and secure variants.

Current operational records:

- `ConnectorConnection`
- `DataSource`
- `IngestionJob`
- `EvidenceRecord`
- `GeneratedArtifact`
- `ConnectorSyncCursor`
- `ConnectorCredential`

Gaps:

- `public_connection()` marks `live_sync_enabled` true when status is `synced`, `syncing`, or `connected` and a credential reference exists.
- `test_connection()` can mark manual/export/provider-assisted/custom connections `ready` without provider authentication.
- Some older routes sanitize and store credential references rather than retrievable encrypted credentials.
- Provider-specific capabilities are mostly route/catalog metadata, not registry-backed implementation behavior.

## Current Upload Flow

Upload paths:

- Legacy `/v1/evidence/upload` is remapped by middleware to `/v1/evidence/upload-stream` when distributed object storage or task queue backends are selected.
- Streamed uploads are bounded by `CONNECTOR_MAX_UPLOAD_BYTES` and spooled by `ingestion_stream.py`.
- Durable staging uses `durable_ingestion_staging.py` with object storage and task outbox.
- Data sources enforce a unique content identity by tenant, connection, and SHA-256.

Risk: do not register another customer `/v1/evidence/upload-stream` implementation.

## Current Queue Flow

Cloudflare Queue:

- Edge source: `cloudflare/edge-gateway/src/index.ts`
- Backend internal processing: `app/api/v1/cloudflare_queue.py`
- Queue token: `CLOUDFLARE_QUEUE_CONSUMER_TOKEN`, with previous-token rotation support.
- Publish URL: `CLOUDFLARE_QUEUE_PUBLISH_URL`
- Publish token: `CLOUDFLARE_QUEUE_PUBLISH_TOKEN`
- Dead-letter behavior is documented in `DEPLOYMENT_TRUTH_MAP.md`.

Redis compatibility:

- `app/services/redis_task_queue.py`

Current behavior:

- Internal Queue auth is separate from customer auth.
- Queue messages are acknowledged only after terminal backend outcomes.
- Transient outcomes raise retryable errors.

## Current Outbox Flow

Outbox:

- Model: `TaskOutbox`
- Publisher: `task_outbox_service.py`
- Durable staging creates an ingestion job and outbox row in one transaction.
- Drainer atomically claims rows as `publishing`.
- Stale `publishing` rows recover after a bounded timeout.
- Workers are expected to be idempotent because a publish can duplicate after remote acceptance but before local commit.

This substrate should be reused for provider synchronization and webhook delivery rather than creating another queue.

## Current R2 Flow

R2/S3-compatible object storage:

- Config in `settings`: `CONNECTOR_OBJECT_STORAGE_BACKEND`, `CONNECTOR_OBJECT_BUCKET`, `CONNECTOR_OBJECT_ENDPOINT_URL`, `CONNECTOR_OBJECT_REGION`, `CLOUDFLARE_R2_ACCESS_KEY_ID`, `CLOUDFLARE_R2_SECRET_ACCESS_KEY`.
- Deployment truth map requires R2 with namespace/checksum safeguards.
- Object storage readiness is evaluated by production readiness and release contracts.

Risk: do not expose object-store paths or internal storage URIs through public Platform API responses.

## Current Quota And Usage Flow

Current Portal usage:

- `UsageEvent` and `QuotaReservation` are organization/workspace/user scoped in `saas.py`.
- Quota operations live in `app/services/quota.py`.
- Commercial upload metering wraps live upload paths.

Legacy usage:

- `UsageMetering` is tenant-scoped.

Gaps:

- Platform API usage must distinguish organization, project, environment, key/service account, operation, cost units, retries, and customer-safe summaries.
- API-key auth must not block on usage commits.

## Current Cloudflare Edge Behavior

Documented behavior:

- Exact browser-origin policy.
- Bounded trusted request IDs and security headers.
- Removal of spoofable internal forwarding headers.
- Fail-closed upstream configuration.
- Recursion protection.
- Bounded retry only for idempotent reads.
- Separate timeout for intelligence routes.
- Connector task envelope validation and Queue production/consumption.
- Scheduled outbox recovery.

Current edge i18n work is active in open PRs and should not be refactored casually.

## Shared Modules Affecting Portal Traffic

Do not casually refactor:

- `agroai_api/app/main.py`
- `agroai_api/app/api/deps.py`
- `agroai_api/app/core/security.py`
- `agroai_api/app/core/config.py`
- `agroai_api/app/models/saas.py`
- `agroai_api/app/api/v1/auth.py`
- `agroai_api/app/api/v1/billing.py`
- `agroai_api/app/api/v1/saas.py`
- `agroai_api/app/services/quota.py`
- `agroai_api/app/services/entitlements.py` if present in later changes
- `agroai_api/app/api/v1/connectors.py`
- `agroai_api/app/api/v1/connector_stream_api.py`
- `agroai_api/app/services/connector_vault.py`
- `agroai_api/app/services/task_outbox_service.py`
- `agroai_api/app/services/redis_task_queue.py`
- `agroai_api/app/services/cloudflare_task_queue.py`
- `agroai_api/app/models/operational_records.py`
- `figma-enterprise-v4/src/app/auth/AuthProvider.tsx`
- `figma-enterprise-v4/src/app/api/client.ts`
- `figma-enterprise-v4/src/app/routes.tsx`
- `figma-enterprise-v4/src/app/components/MainLayout.tsx`
- `cloudflare/edge-gateway/src/index.ts`
- `cloudflare/edge-gateway/src/edge-main-v3.ts`
- `.github/workflows/deploy.yml`
- `docs/DEPLOYMENT_TRUTH_MAP.md`

## Route Compatibility Risks

- Existing Portal routes are all under broad `/v1`.
- Internal Queue routes are also under `/v1/internal`.
- Platform API routes need an explicit non-overlapping namespace, chosen as `/v1/platform/...`.
- Public OpenAPI must be curated from a route manifest, not from the entire FastAPI app.
- Existing Portal JWT routes must not be reclassified or migrated in this branch.

## Database Migration Risks

- Alembic is the sole schema owner.
- Existing migrations are linear through `018_outreach_engagement`; the Platform API foundation extends that chain with `019_platform_api_private_beta`.
- Tests currently use `Base.metadata.create_all`, but production must not.
- New tables must be additive and downgrade-safe.
- Do not backfill legacy tenant keys into organizations.
- Do not rename existing `tenant_id` columns even where they reference `organizations.id` without a separate migration plan.

## Likely Performance Bottlenecks

- Legacy API-key verification commits usage metadata on every successful request.
- Connector list and evidence routes use bounded limits but not a standardized cursor contract.
- Provider calls must not run synchronously inside long Portal requests.
- Usage, webhook delivery, and sync should be queued/outbox-backed or aggregated.
- Rate limiting is currently not enforced by a distributed backend.

## Security Risks

- No-op rate limiter.
- Legacy tenant JWT claim trust is unsuitable for partner API authorization.
- Legacy API-key SHA-256 lacks server-side pepper.
- Connector readiness can appear live based on credential references.
- Provider base URLs require explicit SSRF protections.
- Public OpenAPI could accidentally expose Portal/internal/admin routes without classification.
- Logs and errors must consistently redact secrets.
- Physical action execution must remain disabled and deterministic-approval gated.

## Production Activation Risks

- Platform API readiness must be separate from Portal readiness so missing optional partner contracts do not break Portal health.
- EarthDaily and Valley must remain `awaiting_partner_contract` until official docs, endpoints, credentials, authentication, schemas, rate limits, and successful sandbox calls exist.
- Developer Portal navigation must be feature-flagged and hidden from ordinary customers.
- Valley physical commands must remain disabled.

## Components To Preserve

- Portal JWT authentication and current response contracts.
- Organization, workspace, membership, billing, Stripe, entitlements, quotas, and paywall behavior.
- Existing connector routes and uploads.
- R2/object-storage checksum and namespace safeguards.
- Cloudflare Queue, dead-letter, outbox, worker lease, and release-contract behavior.
- Platform-admin allowlist boundary.
- Existing deployment and rollback contracts.

## Components To Extend

- Add organization-scoped API projects, service accounts, scoped Platform API keys, request logs, usage aggregates, and idempotency records.
- Add explicit Platform API principal dependency separate from Portal `AuthContext`.
- Add route-surface manifest and curated Platform API OpenAPI.
- Add distributed rate-limit abstraction with production fail-closed behavior.
- Wrap current connector vault in an explicit `CredentialVault` interface.
- Add provider adapter registry with EarthDaily and Valley readiness adapters.
- Add webhook endpoint/event/delivery foundations.
- Add SDK foundations and developer-control-plane surfaces behind feature flags.

## Components To Deprecate Later

- Legacy tenant API keys for new enterprise partner access.
- Credential-reference-only connector status.
- Route handlers that encode provider capabilities as display metadata only.
- Demo unauthenticated tenant fallback outside isolated demo routes.
- Offset/unbounded list patterns where future event volumes are high.

## Proposed Platform API Code Boundary

New code should live under additive modules such as:

- `app/models/platform_api.py`
- `app/platform_api/*`
- `app/api/v1/platform_api.py`
- `app/provider_adapters/*`
- `app/webhooks/*`
- `docs/adr/*`
- `sdk/python/agroai_platform/*`
- `sdk/typescript/src/*`

Existing Portal traffic should not import or depend on these modules unless the dependency is explicitly compatibility-neutral and covered by regression tests.
