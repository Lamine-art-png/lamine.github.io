# AGRO-AI Dedicated Demo Environment Runbook

## Objective

Ship a launch/demo portal that uses the **same AGRO-AI codebase and exact release SHA** as the customer portal while keeping billing, customer data, and production connector credentials isolated.

This is not a fork. It is a separate deployment of the same repository.

## Target topology

```text
same git SHA
    |
    +-- Production frontend  https://app.agroai-pilot.com
    |       -> Production API https://api.agroai-pilot.com
    |       -> Production DB / production billing / customer connectors
    |
    +-- Demo frontend        https://demo.agroai-pilot.com
            -> Demo API       https://demo-api.agroai-pilot.com
            -> Dedicated demo DB / no production billing / sandbox-only connectors
```

### Hard invariants

1. Demo and production deploy the same portal/backend release SHA.
2. Demo uses a **dedicated database**. Never point the demo service at production `DATABASE_URL`.
3. Demo does not receive production Stripe secret keys.
4. Demo does not receive customer production connector credentials.
5. All seeded operational data is explicitly evaluation/demo/simulated and has `operational_use=false`.
6. No browser variable can grant an access profile. Access is server-authoritative.
7. Founder/internal full access is an explicit server-side allowlist, not an email check in React.

## Access profiles

### `customer`

Normal commercial behavior. Plan, subscription state, contracts, overrides, and quotas are enforced by the existing commercial control plane.

### `internal`

For explicitly allowlisted AGRO-AI identities. The organization is provisioned through the canonical entitlement override plane as contracted Enterprise with:

- all feature capabilities enabled;
- all quota keys unmetered for the authorized internal organization;
- `billing_required=false`;
- Stripe checkout and billing portal blocked;
- Stripe webhooks ignored for commercial-state mutation.

The verified account email must be present in server secret `INTERNAL_FULL_ACCESS_EMAILS`.

### `demo`

For the dedicated full-access demo identity. Same full-access guarantees as `internal`, plus demo provenance metadata and evaluation/sample data policy.

## Two demo identities

The demo seed creates two deliberately different identities:

1. **Full demo**
   - access profile: `demo`
   - commercial plan projection: Enterprise
   - subscription state: contracted
   - billing required: false
   - premium pages and server capabilities unlocked
   - seeded evaluation portfolio

2. **Free demo**
   - access profile: `customer`
   - plan: Free
   - subscription state: inactive
   - real Free limits and real upgrade/paywall behavior

This lets a launch video demonstrate both the complete product and the Free-to-paid conversion experience without changing code or faking a plan in the browser.

## Seeded full-demo portfolio

The idempotent seed creates these evaluation workspaces:

- Ventura County Avocado Operations
- Coquimbo Table Grapes
- Central Valley Almond Operations

Associated managed entities are tagged with:

```json
{
  "source": "demo_seed",
  "data_class": "simulated_or_evaluation",
  "operational_use": false,
  "customer_data_claim": false,
  "label": "Demo"
}
```

The existing AGRO-AI evaluation seed is reused for sample telemetry/recommendation context. It does not claim live WiseConn, Talgil, OpenET, John Deere, or customer telemetry.

## Backend configuration

Start from:

```text
agroai_api/.env.demo.example
```

Required minimum values:

```text
APP_ENV=demo
APP_URL=https://demo.agroai-pilot.com
API_URL=https://demo-api.agroai-pilot.com
DATABASE_URL=<DEDICATED DEMO DATABASE>
SECRET_KEY=<independent high-entropy value>
WEBHOOK_SECRET=<independent high-entropy value>
NON_CUSTOMER_ACCESS_PROVISIONING_TOKEN=<high-entropy value>
DEMO_AUTO_PROVISION=true
DEMO_FULL_EMAIL=<full demo login>
DEMO_FULL_PASSWORD=<12+ character secret>
DEMO_FREE_EMAIL=<free demo login>
DEMO_FREE_PASSWORD=<12+ character secret>
```

Recommended self-repair allowlist:

```text
DEMO_FULL_ACCESS_EMAILS=<same value as DEMO_FULL_EMAIL>
```

For the founder account in the appropriate backend environment:

```text
INTERNAL_FULL_ACCESS_EMAILS=<verified founder account email>
PLATFORM_ADMIN_EMAILS=<verified founder account email>
```

`PLATFORM_ADMIN_EMAILS` is a separate least-privilege permission for the founder-only customer account directory and CSV export. Do not commit the real email list or passwords to the repository.

## Frontend configuration

Build the same `figma-enterprise-v4` release SHA with:

```text
VITE_API_BASE_URL=https://demo-api.agroai-pilot.com
```

Template:

```text
figma-enterprise-v4/.env.demo.example
```

Never place any secret in a `VITE_*` variable. Vite variables are browser-visible.

## Provisioning

### Automatic dedicated-demo startup

When both conditions are true:

```text
APP_ENV=demo
DEMO_AUTO_PROVISION=true
```

the demo backend idempotently provisions the two demo identities at startup. If explicitly enabled provisioning is misconfigured, startup fails closed instead of silently launching a broken demo.

Production is unaffected because `APP_ENV` must equal `demo`.

### Explicit CLI provisioning

After migrations:

```bash
cd agroai_api
alembic upgrade head
python scripts/provision_demo_environment.py
```

The command prints identity emails, organization IDs/slugs, and creation status. It never prints passwords.

### Token-protected API provisioning

A server/operator can also call:

```text
POST /v1/internal/access/provision-demo-environment
X-AGROAI-Provisioning-Token: <secret>
```

The endpoint is dormant/fail-closed when `NON_CUSTOMER_ACCESS_PROVISIONING_TOKEN` is empty.

## Founder/internal activation

For a verified user whose email appears in `INTERNAL_FULL_ACCESS_EMAILS`:

1. user signs in normally;
2. first authenticated portal context request resolves the server allowlist;
3. the organization is idempotently provisioned through the canonical entitlement system;
4. the browser receives the resulting Enterprise/full-access state;
5. billing remains disabled for that access profile.

No hidden frontend switch, query parameter, request header, or JWT client claim can grant this profile.

## Billing isolation

Internal/demo profiles are protected at three layers:

1. checkout session creation returns `409 billing_not_required`;
2. billing portal creation returns `409 billing_not_required`;
3. authoritative Stripe lifecycle handlers ignore commercial-state mutation for non-customer profiles.

For a demo recording that needs to show checkout, use the genuine Free demo identity with **Stripe test mode only** in the dedicated demo environment.

## Connector policy

Do not copy production customer credentials into demo.

Use one of:

- provider sandbox credentials;
- a dedicated AGRO-AI-owned demo account;
- explicit simulated/evaluation data with visible provenance.

A connector card may be present because the portal code is identical, but connection status must remain truthful.

## Deployment sequence

1. Merge only after CI is green.
2. Record the merged release SHA.
3. Deploy production and demo from that same SHA.
4. Create/verify dedicated demo database.
5. Run Alembic migrations against demo DB.
6. Configure demo backend secrets from `.env.demo.example`.
7. Deploy demo API.
8. Confirm startup provisioning succeeded.
9. Deploy demo frontend with `VITE_API_BASE_URL=https://demo-api.agroai-pilot.com`.
10. Route DNS:
    - `demo.agroai-pilot.com` -> demo frontend
    - `demo-api.agroai-pilot.com` -> demo backend
11. Verify CORS from demo frontend origin. `APP_URL` is automatically added to backend allowed origins.
12. Execute the acceptance matrix below.

## Acceptance matrix

### Full demo identity

- login succeeds;
- `/v1/auth/me` shows Enterprise plan projection;
- entitlements show `access_profile=demo`;
- `billing_required=false`;
- Reports opens without Professional paywall;
- Team opens without Team paywall;
- Requests/Admin opens without Team paywall;
- premium connector surfaces do not show plan locks;
- contract-only capability serialization is projected as enabled;
- AI/deep-analysis quota keys are unmetered for the demo profile;
- direct checkout attempt returns `409 billing_not_required`;
- seeded portfolio workspaces are visible;
- seeded entities retain demo/evaluation provenance.

### Free demo identity

- login succeeds;
- plan remains Free;
- `billing_required=true`;
- Reports shows the real Professional comparison wall;
- Team/Requests show the real Team comparison wall;
- connector locks follow the real packaging matrix;
- upgrade flows remain customer-commercial behavior.

### Production customer regression

- non-allowlisted Free customer remains Free;
- non-allowlisted paid customer still requires active paid state;
- Stripe webhooks still mutate normal customer subscription lifecycle;
- quotas remain finite according to plan/contract;
- no demo startup seed runs unless `APP_ENV=demo` and `DEMO_AUTO_PROVISION=true`.

## Revocation

Token-protected endpoint:

```text
POST /v1/internal/access/revoke
X-AGROAI-Provisioning-Token: <secret>

{
  "organization_id": "..."
}
```

Revocation:

- deletes only `access_profile:*` entitlement overrides;
- restores the commercial plan/status/source snapshot captured at first grant;
- removes non-customer profile metadata.

## Operational note

The codebase now supports the demo environment, but DNS records, deployment service creation, database provisioning, and secret insertion are infrastructure operations. They must be executed in the actual Cloudflare/Render/database control planes; repository code cannot truthfully claim those external resources exist until they are created and verified.
