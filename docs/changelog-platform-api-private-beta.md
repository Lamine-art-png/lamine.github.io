# Changelog: Platform API Private Beta Foundation

- Added Platform API project, service account, key, idempotency, usage, provider capability, identity map, webhook, and action safety models.
- Added `/v1/platform` private-beta route surface.
- Added EarthDaily and Valley integration-readiness adapters.
- Added platform-admin-gated Developers/API Portal page.
- Added Python and TypeScript SDK foundations.
- Added architecture, threat model, rollout, compatibility, and readiness documentation.
- Hardened organization/project/workspace lineage, CIDR enforcement, key rotation validity, and provider/resource restriction enforcement.
- Replaced idempotency read-then-insert with atomic PostgreSQL claims and explicit completed/in-progress/conflict/expiry behavior.
- Added separate versioned AES-GCM webhook secret custody, durable queue-backed delivery, bounded retries/history/manual redelivery, and address-pinned SSRF defenses. Delivery remains disabled by default.
- Changed test project creation to disabled by default.
