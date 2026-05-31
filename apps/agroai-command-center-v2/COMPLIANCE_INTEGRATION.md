# Water Command Center V2 Compliance integration

This directory was not present in the local checkout, so this patch adds the native API-backed Compliance page and navigation descriptor expected by the Water Command Center V2 app without modifying unknown PR 53 files.

Production browser code must not embed tenant API keys. The page uses `credentials: "include"` for an authenticated backend session or secure server-side proxy. For isolated development only, `VITE_NON_PRODUCTION_COMPLIANCE_DEMO_TOKEN` may be provided; it maps to the backend `X-Compliance-Demo-Token` path and has no production permissions.

The page degrades truthfully by showing an API-unavailable state and the compliance disclaimer when `/v1/compliance/*` cannot be reached.
