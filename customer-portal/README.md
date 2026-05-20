# AGRO-AI Water Command Center

The customer portal is a static-compatible enterprise access surface for AGRO-AI. It is designed for customer, investor, OEM, and strategic partner walkthroughs at `https://app.agroai-pilot.com` while keeping production telemetry, provider credentials, and sample data clearly separated.

## Product Story

AGRO-AI turns scattered irrigation data into verified water decisions.

The Water Command Center organizes the operating flow into:

1. Source intake.
2. Intelligence stream.
3. Recommendation.
4. Reconciliation and verification.
5. Report preview.

## Naming

The main product surface is **Water Command Center**. Supporting labels include **Intelligence Engine**, **Decision Engine**, **Source Reconciliation**, **Verification Chain**, and **Report Center**. The portal avoids making model language the headline; the value proposition is verified water action.

## Evaluation Mode

The **Open Water Command Center** path opens the isolated evaluation workspace without production credentials. Sample data is embedded in the portal data module and can also be loaded through the backend Workbench sample package route.

Evaluation mode includes:

- Farms: Alpha Vineyard, Delta Almonds, and West Citrus.
- Blocks: Block A North, Block B West, Almond Block 4, Almond Block East, and Vineyard Block Trial.
- Providers: WiseConn and Talgil evaluation sources.
- Recommendations, confidence, source reconciliation, scheduled/applied/observed/verified states, warnings, report previews, and audit events.

## Input Modes

The Water Command Center shows three intake modes:

- **Connected field** calls `POST /v1/workbench/analyze-live` with default `source: wiseconn` and `entity_id: 162803`. It fails safely when credential-backed telemetry is not provisioned.
- **Upload records** creates a session, uploads customer files, and calls `POST /v1/workbench/sessions/{session_id}/analyze`.
- **Sample data package** loads the expanded Workbench package through `POST /v1/workbench/sample-package`, then analyzes the generated session.

Supported upload file types are CSV, JSON, TXT, and XLSX when the backend has `openpyxl` available.

## Sample Data Package

The expanded package includes:

- `controller_events.csv`
- `weather_summary.csv`
- `soil_moisture.csv`
- `field_notes.txt`
- `flow_meter.csv`
- `crop_profile.json`
- `water_costs.csv`
- `satellite_observation.csv`

The earth-observation file is labeled **Earth observation sample layer** and does not claim a live EarthDaily integration.

## Intelligence Stream

The Water Command Center includes a CSS-only Intelligence Stream:

`Sources -> Normalize -> Reconcile -> Decide -> Verify`

When the user runs intelligence analysis, the stream animates, trace steps activate, the Workbench endpoint is called, and backend `analysis_trace` data fills the step list. On success, recommendation, reconciliation, verification, and report preview sections update from the backend result. On backend failure, the UI shows: **Backend intelligence unavailable. Sample package remains available for evaluation.**

## Backend Setup Request

The Integrations screen includes an active **Request backend setup** flow for WiseConn and Talgil. It opens a setup request modal with:

- Workspace: Alpha Vineyard
- Integration name
- Required backend endpoint: credential vault and tenant provisioning
- Required access: API key, provider account, farm/block mapping
- Security note: credentials must be stored server-side, not in browser storage
- Next action: send setup brief to AGRO-AI technical team

The modal supports copying and downloading the setup brief client-side and adds the audit event **Backend setup request prepared**.

## Live Runtime Routes

The portal preserves existing WiseConn and Talgil runtime status routes and adds the Workbench routes to the command surface:

- `GET /v1/wiseconn/auth`
- `GET /v1/wiseconn/farms`
- `GET /v1/wiseconn/farms/{farm_id}/zones`
- `GET /v1/wiseconn/zones/{zone_id}/irrigations`
- `GET /v1/integrations/talgil/status`
- `GET /v1/integrations/talgil/sensors/latest`
- `GET /v1/integrations/talgil/audit`
- `POST /v1/workbench/analyze-live`
- `POST /v1/workbench/sessions`
- `POST /v1/workbench/sessions/{session_id}/upload`
- `POST /v1/workbench/sessions/{session_id}/analyze`
- `GET /v1/workbench/schema`

## Current Limitations

- Production customer authentication still requires backend identity endpoints.
- Provider credential storage and tenant provisioning must be completed server-side.
- The static portal does not store real provider credentials in browser storage.
- Connected field mode may return a safe limited result when provider telemetry is not provisioned.
- Workbench v1 sessions are in memory unless a persistence layer is added.
- Production report workflows depend on backend report storage/export infrastructure.

## Typography

The portal CSS keeps `"Glacial Indifference", "Inter", "Aptos", "Segoe UI", system-ui, sans-serif` in the primary font stack. No licensed Glacial Indifference font file is committed in this repository.

## Local Preview

```bash
cd customer-portal
python -m http.server 4174
```

Open `http://localhost:4174`.

## Static Deploy Note

1. Deploy `customer-portal/` as static files.
2. Keep API base set to `https://api.agroai-pilot.com` for production.
3. Do not alter Railway secrets, DNS, Cloudflare settings, or infrastructure outside explicit change control.
