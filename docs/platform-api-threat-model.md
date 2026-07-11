# Platform API Threat Model

## Threats And Mitigations

- Cross-organization, project, and workspace access: Platform principals are derived server-side from key records, project rows, service accounts, and organization records. Browser-supplied IDs are not trusted.
- API-key leakage and replay: plaintext is shown once; hashes are never returned; keys can expire, revoke, and rotate. Production requires a pepper.
- Provider credential leakage: credentials remain in AES-GCM vault custody and are never returned to browsers.
- JWT claim spoofing: Platform API partner routes do not accept Portal JWTs.
- Confused deputy behavior: Portal, Platform API, internal Queue, and platform-admin auth dependencies are separate.
- Key-prefix enumeration: prefixes are non-secret identifiers only; verification uses full HMAC hash.
- Idempotency replay: records are scoped by organization, project, operation, key, and request hash.
- Webhook forgery/replay: HMAC signatures, timestamps, event IDs, and secret rotation are designed into the model.
- Rate-limit bypass: production requires Redis-backed project/key-aware limiting.
- Customer key used against internal routes: internal routes use queue tokens, not customer keys.
- SSRF through provider or webhook URLs: provider URL validation and webhook URL validation require HTTPS and block unsafe local/private hosts in production.
- Malicious provider payloads: adapters normalize only known canonical fields and place unknown values in provider extensions.
- Object-store namespace collision: existing R2 namespace/checksum safeguards are preserved.
- Cursor corruption and duplicate provider records: provider identity maps and cursor records are organization-scoped; cursor advancement must follow durable commits.
- Unauthorized physical execution: action execution is disabled, and kill-switch configuration defaults disabled.
- Secret leakage through logs/errors/OpenAPI: public OpenAPI is manifest-curated; key hashes and credential material are excluded from responses.
- Platform-admin confused with organization owner: platform-admin status does not become organization access unless a route explicitly uses the admin dependency.

## Residual Risks

- Redis rate-limit production behavior still needs a deployed backend proof.
- Webhook delivery worker execution is modeled but not live-delivering by default.
- Provider schemas cannot be validated against EarthDaily or Valley until official contracts arrive.
