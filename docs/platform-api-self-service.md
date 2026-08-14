# Self-service developer platform

## What is implemented

AGRO-AI has one server-authoritative Platform API developer product with two launch states: a reviewed private-beta fallback and a public TEST self-service mode.

The TEST self-service implementation includes:

- Platform-specific registration and sign-in on `platform.agroai-pilot.com`;
- automated agricultural organization verification and required email verification;
- exact current developer-agreement presentation and versioned server-side acceptance;
- automatic `developer_self_service` entitlement for eligible verified owner/admin users;
- TEST projects only, with server-assigned project/service-account/key/webhook limits;
- service accounts and scoped `agro_test_` keys with one-time plaintext display, rotation and revocation;
- deterministic project-scoped synthetic agricultural sandbox data;
- fields, sources/uploads, observations, recommendations, reports, jobs, usage, request logs and provider-readiness resources;
- keyless authenticated browser Playground;
- first-party browser/device CLI authentication with organization binding, atomic single-winner exchange and server-side logout revocation;
- CLI project, service-account, key, field, usage, job and webhook operations;
- `agroai bootstrap`, which creates TEST project → TEST-safe service account → one-time TEST key;
- public macOS/Linux and Windows installers served from AGRO-AI's own Platform assets;
- Python and TypeScript SDK foundations and reproducible package artifacts;
- PostgreSQL/Redis integration, BOLA/IDOR, secret-sink, contract-drift and release gates.

## Public TEST journey

After the protected public activation is live, an eligible developer can use the browser path:

```text
platform.agroai-pilot.com
→ create verified agricultural organization account
→ verify email
→ sign in as owner/admin
→ read current developer agreements
→ accept exact effective versions
→ automatic TEST enrollment
→ Developer Console
→ TEST project
→ service account
→ agro_test_ key
→ first API call
```

No salesperson or API-access reviewer is part of that eligible TEST path.

The terminal path is:

```bash
curl -fsSL https://agroai-pilot.com/platform-api/assets/install.sh | sh
agroai login
agroai --json bootstrap --name "First AGRO-AI integration"
export AGROAI_API_KEY="agro_test_..."
agroai doctor
agroai fields list --json
```

Windows developers can install with:

```powershell
iwr https://agroai-pilot.com/platform-api/assets/install.ps1 -UseBasicParsing | iex
```

## Safety boundary

Automatic self-service is TEST-only.

TEST enrollment cannot grant:

- LIVE projects;
- automatic LIVE approval;
- production provider credentials or provider writes;
- another organization's data;
- production customer data;
- production webhook delivery;
- billing/Stripe activation;
- physical irrigation or other physical agricultural execution.

TEST projects are never promoted to LIVE in place. LIVE remains a separately reviewed contractual and technical path.

The CLI's default bootstrap scopes do not include physical execution or provider-write scopes. A human CLI session is never substituted for a machine API key, and a machine API key is never treated as human identity.

## Legal activation boundary

The code cannot manufacture legal approval.

Draft review material exists under `platform-api/legal/drafts/` and is explicitly marked `LEGAL REVIEW REQUIRED — NOT EFFECTIVE`.

Public automatic enrollment remains fail closed until an exact counsel-approved catalog and exact matching public legal assets are committed and validated. The catalog must include real reviewer/approval evidence and SHA-256 digests. The protected activation workflow then publishes matching `approved_effective` database records before automatic enrollment is enabled.

## Production activation

The authoritative activation workflow is:

`.github/workflows/platform-api-public-self-service-activation.yml`

It performs a two-stage release:

1. validate current `main`, production credentials and real counsel-approved legal evidence;
2. enable terms enforcement while auto-enrollment/device auth remain off;
3. deploy exact main SHA;
4. publish and verify exact effective legal records;
5. enable only the TEST developer control plane, TEST projects, sandbox, auto-enrollment and CLI device auth;
6. explicitly force LIVE/provider/webhook/physical/billing flags off;
7. deploy exact main SHA again and verify production Platform health;
8. switch the narrow Platform marketing Worker to public TEST copy and indexing;
9. verify public legal assets, installer identity and launch state;
10. persist the public-launch repository variable and upload immutable evidence.

Ordinary code deployment does not flip public self-service on.

## Rollback

`.github/workflows/platform-api-public-self-service-rollback.yml` closes new public auto-enrollment and CLI device acquisition, restores private-beta marketing/noindex, and keeps all dangerous capabilities off. It deliberately does not destroy existing developer projects, enrollments or keys merely to close public acquisition.

## Package distribution

The CLI is usable without waiting for PyPI, npm or Homebrew ownership because the public installers install directly from the official AGRO-AI repository source archive.

Registry publication remains optional additional distribution. AGRO-AI must not advertise a PyPI/npm/Homebrew install method until the exact namespace and publishing credentials are verified.

## Current truth rule

Implementation completion and production activation are different facts.

The repository may be described as supporting public TEST self-service only after this code is merged and its release gates are green. The service itself may be described as publicly self-service only after the protected activation workflow has succeeded against real counsel-approved legal evidence and the exact production release.
