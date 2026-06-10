# Global Compliance Kernel v2

The global compliance kernel keeps all packs disabled by default except the controlled California internal alpha metadata exposed through the feature-gated API. Arizona remains `disabled_alpha`; research templates remain `disabled_research_only`.

Security posture:

- `CALIFORNIA_COMPLIANCE_PACK_ENABLED=false` by default.
- `COMPLIANCE_DEMO_FIXTURES_ENABLED=false` by default.
- `COMPLIANCE_DEMO_TOKEN` defaults to an empty string.
- Demo access is pinned to the approved California fixture tenant only.
- Production tenant scope must come from a verified server-side API key.
- `X-Organization-Id` is never authority and is rejected when it conflicts with the authenticated tenant.
- Browser tenant API keys are forbidden until a secure browser-session or short-lived token flow exists.

Export posture:

- Direct regulatory filing is out of scope.
- Truth labels are required on material values.
- OpenET-derived values are imported as `estimated`.
- Unsupported object-storage backends fail closed because object storage is not implemented in this sprint.
