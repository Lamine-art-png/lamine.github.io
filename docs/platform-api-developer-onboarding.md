# Platform API Developer Onboarding

The private beta flow is intentionally gated.

1. Platform administrator enables the developer control plane for an internal organization.
2. Create a test API project.
3. Create a service account with least-privilege scopes.
4. Create a scoped test API key.
5. Copy the plaintext key once.
6. Call `/v1/platform/me`.
7. Inspect `RateLimit-*` headers and `request_id`.
8. Configure webhooks only with HTTPS endpoints.

Live projects, EarthDaily sandbox access, Valley sandbox access, and physical irrigation commands require later reviewed activation.
