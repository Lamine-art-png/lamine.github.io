# Talgil Preservation Note (Internal)

## What is preserved in this phase

- Talgil-specific portal integration points are isolated as TODO adapters in `customer-portal/js/apiClient.js`.
- Portal shell is built to consume future controller-provider data without changing production Railway backend behavior.

## What is intentionally not live yet

- No Talgil write calls, secrets, or controller provisioning changes are introduced.
- No Cloudflare Worker or Railway deployment path changes are introduced in this branch.

## What remains before Talgil deployment

1. Reconcile and cherry-pick only clean Talgil integration commits from the dedicated Talgil workstream/branch (not present in this checkout).
2. Add tenant-scoped Talgil endpoints in backend API and expose them in OpenAPI.
3. Connect portal adapters to those finalized endpoints and add end-to-end verification tests.
