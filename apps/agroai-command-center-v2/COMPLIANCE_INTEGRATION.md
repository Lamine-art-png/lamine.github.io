# Compliance integration boundary

The Water Command Center V2 Compliance page is surgically integrated into the upstream AppShell, Sidebar, and command store. It is feature-flagged in navigation and uses API-backed values only.

Production browser code must not embed tenant API keys. This repository does not yet contain a production browser-session or short-lived compliance-token dependency that derives tenant scope server-side. Until that exists, the V2 Compliance browser client fails closed unless `VITE_NON_PRODUCTION_COMPLIANCE_DEMO_TOKEN` is configured for an explicitly labeled non-production demo. Production compliance access remains server-to-server through verified backend API keys.
