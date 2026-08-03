# Platform API security baseline

The Platform API uses organization, project, service-account and workspace scoped keys; server-side HMAC hashing with a dedicated pepper; one-time plaintext display; least-privilege scopes; optional CIDR restrictions; rotation overlap; immediate revocation; and fail-closed lineage checks. Customer API keys are separate from Portal sessions and internal Queue credentials.

Production requires a distributed fail-closed Redis limiter, authenticated Cloudflare-to-origin client context, PostgreSQL, durable object storage and queue custody, explicit versioned AES-GCM keyrings, curated public OpenAPI, bounded idempotency, signed webhooks, safe request metadata, and exact-release verification. Physical control execution remains disabled unless separately implemented and approved.

## Still required for broad enterprise claims

Independent penetration testing, SOC 2 or applicable ISO audit work, SSO, enforced MFA and SCIM, approved legal and DPA text, data-export and deletion workflows, regional residency controls, customer-specific retention, verified backup restores, and sustained production SLO evidence are external or multi-quarter controls. They must never be implied by a passing unit test or deployment gate.
