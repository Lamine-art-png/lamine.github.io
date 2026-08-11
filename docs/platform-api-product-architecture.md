# Platform API product architecture

Status: implemented behind disabled server flags; external activation is not part
of this change.

One organization-scoped control plane serves five programs: `internal`,
`developer_private_beta`, `developer_self_service`, `strategic_partner`, and
`enterprise_custom`. Programs do not duplicate projects, service accounts, API
keys, quota records, request logs, webhooks, provider adapters, object storage,
Queue, or billing. An enrollment narrows environments, resource counts, scopes,
providers, resources, retention, support, quota, and billing mode.

The two distribution tracks share that platform:

- Strategic partners enter through a reviewed application, dossier, documented
  contract blockers, vault references, and manual test/live grants.
- Self-service developers enter through organization verification, active
  owner/admin membership, enrollment, a versioned API plan, and test projects.

Authorization is evaluated at request time. Organization verification,
enrollment, environment, subscription, live approval, project, service account,
key, CIDR, scope, provider, resource, quota, and feature flags all fail closed.
Human Portal sessions are never machine identities, and platform administrators
use separate administrative routes.

The data path is `edge -> FastAPI -> PostgreSQL/Redis -> durable outbox -> Queue
worker -> provider/storage/Stripe`. Customer API operations reserve credits
before work and reconcile once after the logical operation. Internal retries do
not create another reservation or meter event.

See `docs/adr/006-platform-api-programs.md`,
`docs/adr/007-platform-api-credit-authority.md`, and
`docs/platform-api-threat-model.md`.
