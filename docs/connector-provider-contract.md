# Connector Provider Contract

Provider-specific code must live behind a provider adapter.

Adapters expose:

- metadata;
- configuration schema;
- credential schema;
- credential validation;
- resource discovery;
- normalization;
- cursor/pagination contract where implemented;
- capability and readiness status.

Capability status derives from adapter behavior, credential state, contract state, and successful validation. Marketing copy alone must not mark a capability live.

Production provider URLs require allowlisting, HTTPS, no userinfo, bounded timeouts, safe redirects, and SSRF protections.
