# AGRO-AI Enterprise Customer Portal

The customer portal is a static-compatible Enterprise Demo and Customer Portal for AGRO-AI. It is designed for customer demos, investor demos, and integration partner demos at `https://app.agroai-pilot.com` while keeping production data and demo data clearly separated.

## Portal purpose

The portal demonstrates AGRO-AI's full irrigation operating chain:

1. Connect controller environments.
2. Assemble normalized live context.
3. Generate water recommendations.
4. Show execution tasks and schedule status.
5. Track applied controller events and field observations.
6. Verify outcomes and prepare executive reporting.

## Demo mode

The **Launch Demo Environment** path opens the isolated `AGRO-AI Demo Workspace` without credentials. Demo data is embedded in `customer-portal/js/demoData.js` and is clearly marked as demo data in the UI.

Demo mode includes:

- Demo farms: Alpha Vineyard, Delta Almonds, and West Citrus.
- Demo zones: Block A North, Block B South, Pump Zone 3, and Citrus East Line.
- Demo providers: WiseConn demo connection and Talgil demo connection.
- Demo recommendations, confidence, data quality, scheduled/applied/observed/verified states, warnings, report previews, and audit events.

## Enterprise clarity surfaces

The Command Center now includes buyer-facing explanation surfaces designed for a 90-second sales walkthrough:

- A high-contrast sidebar with an **OPERATIONS** navigation label and readable **Mode: Demo / Alpha Vineyard workspace** footer.
- An ROI and compliance strip for YTD water saved, avoided dollar value, SGMA-ready posture, evidence completeness, and demo-mode financial assumptions.
- An **AI Decision Pipeline** showing signal ingest, field-context normalization, source reconciliation, and recommendation generation.
- A **From noisy data to verified action** panel that shows raw signals, AGRO-AI reconciliation, and clean action.
- A **Cross-system reconciliation** panel that explicitly marks the Talgil row as available but pending target selection, without making live target telemetry claims.
- Intelligence Engine framing for normalization, reconciliation, recommendation, and verification planning.

## Live mode

The **Customer Login** path is an auth-ready scaffold for a future backend identity flow. It does not claim production authentication. After entry, live mode loads available runtime information from `https://api.agroai-pilot.com`.

Live mode currently uses:

- `GET /v1/wiseconn/auth`
- `GET /v1/wiseconn/farms`
- `GET /v1/wiseconn/farms/{farm_id}/zones`
- `GET /v1/wiseconn/zones/{zone_id}/irrigations`
- `GET /v1/decisioning/blocks/{block_id}/water-state`
- `GET /v1/decisioning/blocks/{block_id}/water-state/history`
- `GET /v1/execution/blocks/{block_id}/decisions`
- `GET /v1/execution/blocks/{block_id}/verifications`
- `POST /v1/intelligence/recommend/live/wiseconn/162803`
- `GET /v1/integrations/talgil/status`
- `GET /v1/integrations/talgil/sensors/latest`
- `GET /v1/integrations/talgil/audit`
- `GET /v1/reports/roi` when enabled by the deployed API

Live recommendations support optional in-memory overrides for crop type, soil type, irrigation method, ETo, rain forecast, and field observation. Overrides are not stored in browser localStorage.

## Interactive demo runtime

Demo mode includes an in-browser runtime state machine. It can select farms and zones, switch scenarios, generate a demo recommendation, schedule it, mark applied water, record a field observation, verify the outcome, generate report previews, print the report, export CSV, and update the audit log without a page reload. Runtime state is kept in memory and may be mirrored to `sessionStorage`; it is demo-only and is not production telemetry.

## Live WiseConn recommendation behavior

Live mode can call `POST /v1/intelligence/recommend/live/wiseconn/162803` with optional in-memory overrides for crop type, soil type, irrigation method, ETo, rain forecast, and field observation. Successful live calls update the recommendation artifact and live audit events. Failed calls show customer-safe errors and do not break demo mode.

## Backend capabilities still required

Production customer authentication, organization selection, secure provider credential storage, controller execution capture, persisted audit history, and production report generation require backend endpoints before they can be used as live customer operations.

## Integration onboarding flow

The Integrations screen presents a backend-ready provider activation flow:

1. Select provider.
2. Enter credentials or API key.
3. Test connection.
4. Sync farms/controllers.
5. Activate intelligence.

Provider credential submission intentionally requires secure backend credential endpoints. The static portal does not store real provider secrets in browser localStorage.

## What is real today

- API base: `https://api.agroai-pilot.com`
- Portal domain: `https://app.agroai-pilot.com`
- WiseConn runtime is live.
- Talgil runtime is live.
- Intelligence Engine is live.
- Input normalization is live.
- Live context endpoints are live.
- Live WiseConn recommendation is supported for zone `162803`.

## What is simulated demo data

Embedded demo farms, demo zones, demo recommendations, demo report previews, demo audit events, and demo provider cards are simulated and clearly labeled as demo data. They are not mixed with live production telemetry.

## What still requires backend auth or credential storage

- Production customer authentication.
- Organization selector population after login.
- User and role administration.
- Secure provider credential storage and rotation.
- Production report generation workflows where not yet enabled by the deployed API.

## Typography

The portal CSS uses `"Glacial Indifference", "Inter", "Aptos", "Segoe UI", system-ui, sans-serif` as its primary font stack. No licensed Glacial Indifference font file is committed in this repository; the site owner should add and wire a licensed asset in production if brand typography requires the exact face.

## Local preview

```bash
cd customer-portal
python -m http.server 4173
```

Open `http://localhost:4173`.

## Static deploy note (`app.agroai-pilot.com`)

1. Deploy `customer-portal/` as static files.
2. Point `app.agroai-pilot.com` to that static host through normal infrastructure change control.
3. Keep API base set to `https://api.agroai-pilot.com` for production.
4. Do not alter Railway secrets, DNS, Cloudflare settings, or infrastructure outside explicit change control.
