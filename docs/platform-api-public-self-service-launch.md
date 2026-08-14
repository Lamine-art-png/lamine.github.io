# AGRO-AI Platform API — public TEST self-service launch

## Goal

A verified agricultural developer can discover AGRO-AI, create an account, accept the effective developer agreements, activate a bounded TEST entitlement, install the CLI, sign in, create a TEST project/service account/key, and call deterministic agricultural TEST resources without contacting sales or waiting for an API-access reviewer.

This launch does **not** enable LIVE projects, production provider credentials, physical execution, production webhook delivery, or automatic LIVE approval.

## User journey

Browser:

1. Open `https://platform.agroai-pilot.com`.
2. Create a developer organization account.
3. Pass the existing automated organization verification boundary.
4. Verify email.
5. Sign in as an owner/admin.
6. Review the current effective Platform API legal catalog.
7. Accept each required document with its exact version and content digest.
8. The server grants the tested `developer_self_service` TEST-only enrollment.
9. The Developer Console opens immediately.

Terminal:

```bash
curl -fsSL https://agroai-pilot.com/platform-api/assets/install.sh | sh
agroai login
agroai --json bootstrap --name "First AGRO-AI integration"
export AGROAI_API_KEY="agro_test_..."
agroai doctor
agroai fields list --json
```

`agroai login` uses the first-party browser/device authorization flow. `bootstrap` creates a TEST project, TEST-safe service account, and one-time `agro_test_` key. It never requests LIVE or physical-action permission.

## Production activation prerequisites

All prerequisites are mandatory and fail closed.

### Legal evidence

Public automatic enrollment requires an exact counsel-approved legal catalog. The repository intentionally does not treat draft legal text as approval.

Required:

- `platform-api/legal/approved-catalog.json` with `status: "counsel_approved"`;
- exact versioned public legal HTML assets under `platform-api/assets/legal/`;
- SHA-256 digests in the catalog that match those exact public assets;
- counsel approval date and reviewer record in the catalog;
- a production Platform administrator bearer token available only to the protected activation environment so the workflow can publish matching `approved_effective` database records.

The workflow must stop before any customer-facing auto-enrollment flag is enabled if legal evidence is missing, malformed, or digest-mismatched.

### Production infrastructure

Required before activation:

- production Render service ID (`vars.PRODUCTION_API_SERVICE_ID`);
- Render API token with permission to update that service (`secrets.RENDER_API_KEY`);
- production Platform admin bearer token (`secrets.PLATFORM_API_ACTIVATION_ADMIN_TOKEN`);
- non-default application `SECRET_KEY` so CLI device-code hashing and human session signing remain production-safe;
- production `PLATFORM_API_KEY_PEPPER`;
- Redis-backed Platform rate limiter, fail-open disabled;
- reviewed edge/origin authentication secret;
- current DB migration head and production-readiness contract green;
- Cloudflare Portal and Platform host release healthy.

## TEST flags enabled by the activation workflow

The protected activation workflow sets these directly on the production API service:

```text
PLATFORM_API_ENABLED=true
PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED=true
PLATFORM_API_TEST_PROJECTS_ENABLED=true
PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED=true
PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED=true
PLATFORM_API_TERMS_ENFORCEMENT_ENABLED=true
PLATFORM_API_CLI_DEVICE_AUTH_ENABLED=true
PLATFORM_API_PUBLIC_DOCS_ENABLED=true
```

Where already enabled, values remain unchanged.

## Capabilities forced off during TEST launch

The activation workflow also explicitly writes these values to `false` so a stale production environment cannot accidentally widen the launch:

```text
PLATFORM_API_LIVE_PROJECTS_ENABLED=false
PLATFORM_API_LIVE_ACCESS_REQUESTS_ENABLED=false
PLATFORM_API_WEBHOOK_DELIVERY_ENABLED=false
PLATFORM_API_LIVE_AUTO_APPROVAL_ENABLED=false
EARTHDAILY_ADAPTER_ENABLED=false
VALLEY_IRRIGATION_ADAPTER_ENABLED=false
VALLEY_IRRIGATION_WRITE_CAPABILITY_ENABLED=false
```

Billing/Stripe activation is not part of this launch.

## Two-stage legal activation

The backend intentionally requires `PLATFORM_API_TERMS_ENFORCEMENT_ENABLED=true` before the Platform admin terms endpoint can publish an effective document. The launch workflow therefore uses two short, explicit deployment stages:

1. enable terms enforcement only and deploy the exact main commit;
2. publish the counsel-approved terms records through `/v1/platform/admin/terms/{type}/{version}` using the protected Platform admin token;
3. verify all records and digests;
4. enable the remaining TEST self-service flags and deploy the same exact main commit;
5. verify the production environment and public health contract.

Automatic TEST enrollment is not enabled during stage 1.

## Rollback

The same Render API boundary can immediately set the following to false and redeploy:

```text
PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED=false
PLATFORM_API_CLI_DEVICE_AUTH_ENABLED=false
PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED=false
PLATFORM_API_TEST_PROJECTS_ENABLED=false
```

Existing keys and enrollments remain auditable. If security requires a stronger response, suspend affected enrollments/keys using the existing server-side controls. Do not enable LIVE as part of rollback.

## Public distribution

The official CLI has a no-registry installation path served from AGRO-AI's own Platform API assets. PyPI, npm and Homebrew publication are useful additional channels but are not prerequisites for a developer to install and use the CLI.

Registry publication must remain truthful: package names and credentials must be verified before advertising those install methods.

## Launch completion criteria

Public TEST self-service is considered launched only when all of the following are evidenced on the same release:

- protected activation workflow completed successfully;
- production Render env values match the TEST-only contract;
- counsel-approved legal records and public assets have exact matching digests;
- Platform/Portal production release is green;
- `PLATFORM_API_CLI_DEVICE_AUTH_ENABLED` is ready, not merely configured;
- physical execution remains disabled;
- provider-backed LIVE adapters remain disabled/contract-gated;
- production webhook delivery remains disabled;
- a real new-user smoke completes register → verify → terms → auto-enroll → TEST project → service account → `agro_test_` key → API call;
- `agroai login` browser approval works on the public product;
- `agroai bootstrap` creates a TEST chain and the returned key succeeds at `/v1/platform/me`.

No documentation or CI assertion may call the launch complete before those conditions are true.
