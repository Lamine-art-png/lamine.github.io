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
- Rebased after account verification and linearized the unpublished migrations as `019_account_verification` → `020_platform_api_private_beta` → `021_platform_api_hardening`; no merge revision or sibling head remains.
- Unified Portal JWT, Developer control-plane, and Platform API key organization access around the server-owned `approved` / `approved_legacy` policy. Existing keys fail immediately when their organization becomes unapproved.
