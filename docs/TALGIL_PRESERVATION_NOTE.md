# Talgil Preservation Note (Internal)

## What is preserved in this phase

- Talgil-specific integration artifacts remain preserved in-repo (notably under `agroai-cloudflare-worker/api-native/`).
- Portal now consumes a source-aware summary route (`GET /v1/controllers/environments`) to present Talgil truthfully as an integration-ready environment.

## What is intentionally not live yet

- No Talgil write calls, secrets, or controller provisioning changes are introduced.
- No Cloudflare Worker or Railway deployment path changes are introduced in this branch.

## What remains before Talgil deployment

1. Reconcile and cherry-pick only clean Talgil integration commits from the dedicated Talgil workstream/branch (not present in this checkout).
2. Add tenant-scoped Talgil endpoints in backend API and expose them in OpenAPI.
3. Connect portal adapters to those finalized endpoints and add end-to-end verification tests.

## What is intentionally not faked

- No fake Talgil telemetry rows are generated.
- No fake Talgil recommendations or verification events are shown.
- No Talgil write-path calls are exposed from this FastAPI deployment until real runtime wiring exists.
