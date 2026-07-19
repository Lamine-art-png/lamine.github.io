# Platform API Threat Model

## Threats And Mitigations

- Cross-organization, project, and workspace access: Platform principals are derived server-side from key records, project rows, service accounts, and organization records. Browser-supplied IDs are not trusted.
- API-key leakage and replay: plaintext is shown once; hashes are never returned; keys can expire, revoke, and rotate. Production requires a pepper.
- Provider credential leakage: credentials remain in AES-GCM vault custody and are never returned to browsers.
- JWT claim spoofing: Platform API partner routes do not accept Portal JWTs.
- Confused deputy behavior: Portal, Platform API, internal Queue, and platform-admin auth dependencies are separate.
- Key-prefix enumeration: prefixes are non-secret identifiers only; verification uses full HMAC hash.
- Idempotency replay: PostgreSQL-safe atomic claims are scoped by organization, project, operation, key, and request hash. Matching completed requests replay, live claims return `operation_in_progress`, conflicting payloads return 409, and expired claims are atomically reclaimed.
- Webhook forgery/replay: outgoing deliveries use HMAC signatures over timestamp, event ID, and body. Secrets use a separate versioned AES-256-GCM keyring with organization/project/endpoint associated data and bounded rotation overlap.
- Rate-limit bypass: production requires Redis-backed organization/project/key-aware limiting with atomic burst and sustained counters.
- Customer key used against internal routes: internal routes use queue tokens, not customer keys.
- CIDR header spoofing: the Cloudflare edge strips all incoming forwarding headers and writes client IP only alongside a dedicated edge-to-origin secret. Render rejects unauthenticated forwarding context and allowlisted keys fail closed when identity is unavailable.
- SSRF through provider or webhook URLs: webhook URLs require HTTPS on approved ports, reject credentials and all non-global IPv4/IPv6 classes, resolve every DNS answer, pin the validated address for the connection, bound redirects, and repeat validation after each redirect.
- Malicious provider payloads: adapters normalize only known canonical fields and place unknown values in provider extensions.
- Object-store namespace collision: existing R2 namespace/checksum safeguards are preserved.
- Cursor corruption and duplicate provider records: provider identity maps and cursor records are organization-scoped; cursor advancement must follow durable commits.
- Unauthorized physical execution: action execution is disabled, and kill-switch configuration defaults disabled.
- Secret leakage through logs/errors/OpenAPI: public OpenAPI is manifest-curated; key hashes and credential material are excluded from responses.
- Platform-admin confused with organization owner: platform-admin status does not become organization access unless a route explicitly uses the admin dependency.

## Residual Risks

- Redis rate-limit code paths are covered by shared-backend contract tests; production rollout still requires operator-configured Redis and readiness evidence for the deployed environment.
- Webhook delivery remains disabled by default and requires the queue transport, webhook AES keyring, authenticated Cloudflare queue boundary, and explicit delivery flag before any network request.
- Provider schemas cannot be validated against EarthDaily or Valley until official contracts arrive.
