# Platform API Versioning And Deprecation

- URL version: `/v1/platform`.
- Public OpenAPI version: `2026-07-private-beta`.
- Webhook event version: `2026-07-10`.
- Provider adapter contract version: `provider-adapter-v1`.

Backward-compatible additions may ship inside `/v1/platform`. Breaking changes require a new version or explicit private-beta migration notice.

Deprecations must include:

- documented replacement;
- deprecation date;
- sunset date when known;
- response headers for deprecated public routes;
- changelog entry.
