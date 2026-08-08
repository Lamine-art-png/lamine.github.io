# AGRO-AI Platform API enterprise readiness — 2026

Status: **production-capable controlled launch; broad-enterprise parity not yet certified**.

This is the authoritative readiness record. “OpenAI-level” or “Anthropic-level”
is not a self-awarded certification. The comparison is useful only as an
engineering benchmark for security, reliability, privacy, developer experience,
and operational maturity.

## Verified technical controls

| Domain | Current evidence |
| --- | --- |
| Tenant boundary | Organization, project, service-account, workspace, provider, and resource lineage checks; cross-tenant denial tests. |
| Machine identity | Test/live key separation, HMAC+pepper storage, scoped permissions, expiration, CIDR restrictions, rotation overlap, revocation. |
| Request safety | Server request IDs, bounded customer correlation IDs, cursor pagination, idempotency and concurrency tests, safe error envelopes. |
| Traffic control | Redis-backed multi-dimensional limiter designed to fail closed in production. |
| Secret custody | Versioned AES-256-GCM connector and webhook keyrings; one-time plaintext display; retrieval audit. |
| Webhooks | Signed delivery, timestamp/event identifiers, SSRF controls, bounded response capture, retries, terminal failure, replay controls. |
| Data custody | PostgreSQL system of record, durable queue/outbox patterns, checksum-bound object storage, no raw storage paths in customer responses. |
| Billing | Live Stripe Checkout, Customer Portal, signed/deduplicated webhooks, usage reservation/export/reconciliation, interval-safe prices. |
| Contract quality | Curated Platform-only OpenAPI with CI drift/leak checks; Python and TypeScript SDK source and tests. |
| Operations | Readiness endpoints, status/incident foundation, support cases, audit events, abuse controls, exact-SHA deployment verification. |

## Launch blockers before “all enterprise customers”

| Requirement | State | Completion evidence |
| --- | --- | --- |
| Measured performance | Open | Controlled load/saturation reports on the declared paid production topology. |
| Availability history | Open | At least 30 days of SLO telemetry and reviewed incidents. |
| Disaster recovery | Open | Successful isolated PostgreSQL/object-store restore drill with achieved RPO/RTO. |
| Independent security review | Open | Remediated third-party penetration test and recurring vulnerability program. |
| Compliance | Open | Applicable SOC 2/ISO audit evidence; no certification claim before issuance. |
| Enterprise identity | Open | SAML/OIDC SSO, enforced MFA policy, and SCIM/domain lifecycle where contracted. |
| Privacy operations | Open | Approved DPA/privacy terms, customer export/deletion, configurable retention, residency/ZDR where sold. |
| SDK distribution | In progress | Signed release artifacts now supported; registry publication and support policy required. |
| Legal launch | Open | Counsel-approved API Terms, AUP, Privacy, DPA, SLA, and enterprise order form. |
| Customer operations | Open | Named on-call/customer-success coverage and at least one repeated real enterprise integration. |

## Customer eligibility now

Approved organizations can build controlled server-side integrations using the
reviewed Platform API surface. Physical irrigation writes and providers marked
`awaiting_partner_contract` remain unavailable. Customers requiring SSO, SCIM,
formal SLA, custom residency/ZDR, a completed security questionnaire backed by
certification, or multi-region contractual recovery must use an explicitly
reviewed enterprise agreement and cannot be represented as self-service-ready
until those controls exist.
