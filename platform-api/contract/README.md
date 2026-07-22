# Platform API contract — source of truth

The AGRO-AI developer platform (landing, documentation, reference, and the
authenticated console) must **never invent** endpoints, key prefixes, or
response shapes. Everything public is derived from one artifact:

- **`platform_api_openapi.json`** — the curated public contract, produced
  **only** by the backend's own generator (`GET /v1/platform/openapi.json`,
  which is gated by `PLATFORM_API_PUBLIC_DOCS_ENABLED` and includes only the
  routes flagged `public_openapi=True` in
  `agroai_api/app/platform_api/route_manifest.py`).
- **`platform_api_openapi.sha256`** — canonical digest of that contract,
  matching the backend's reviewed snapshot at
  `agroai_api/tests/contracts/platform_api_openapi.sha256`.

## Regenerate

```bash
python3 platform-api/contract/generate_contract.py          # write snapshot
python3 platform-api/contract/generate_contract.py --check  # CI: verify only
```

`--check` fails when the committed snapshot drifts from the backend, when the
digest no longer matches the reviewed backend snapshot, when a private / admin
/ developer-control-plane route leaks into the public contract, or when a
documented path is not under `/platform/`. It runs in CI via
`.github/workflows/platform-api-contract-ci.yml`.

## What this guarantees

- Real routes only, all under `/v1/platform/*`.
- First-party key prefixes only: `agro_test_`, `agro_live_`.
- Developer control-plane routes (`/v1/platform/developer/*`, `portal_jwt`
  auth) are **excluded** from public docs — they are consumed by the
  authenticated console, not advertised as public API.
- Commercial surfaces (pricing, SLAs, live projects, webhooks-as-available,
  self-service) are gated by the corresponding `PLATFORM_API_*` feature flags,
  all of which default to `False` (private-beta state).
