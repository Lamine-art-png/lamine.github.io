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

The **Open Water Command Center** path opens the isolated evaluation workspace without production credentials. On entry the **representative data** package is preloaded and a verified decision is rendered immediately, so the portal is functional in a founder-led call before any source is configured. Representative records are embedded in the portal data module and can also be loaded through the backend Workbench sample package route.

A discreet **Representative data** provenance badge in the header signals that representative records are used until production targets are connected.

Evaluation mode includes:

- Workspace scenarios (title switcher): Alpha Vineyard, Almond Orchard, Multi-Farm Portfolio, and Partner Data Validation. Each loads representative records and updates the decision, source intelligence, reconciliation, and report preview.
- Farms: Alpha Vineyard, Delta Almonds, and West Citrus.
- Blocks: Block A North, Block B West, Almond Block 4, Almond Block East, and Vineyard Block Trial.
- Providers: WiseConn and Talgil evaluation sources.
- Recommendations, confidence, source reconciliation, scheduled/applied/observed/verified states, warnings, report previews, and audit events.

## Source Modes

Source setup is moved off the primary screen into a right-side drawer opened from **Add or manage sources** in the Source intelligence header. The drawer has four tabs:

- **Connected systems** — WiseConn (Live-ready), Talgil (Runtime reachable), Generic controller (Available). Each opens an integration setup brief; no live telemetry is claimed.
- **Upload records** — drag-and-drop / file picker. Creates a session, uploads via `POST /v1/workbench/sessions/{session_id}/upload`, shows detected type, parse status, and warnings, then **Analyze uploaded records** calls `POST /v1/workbench/sessions/{session_id}/analyze`.
- **API access** — ingestion endpoint, server-side authentication requirement, accepted payload categories, schema link, and a copyable API setup brief.
- **Partner feeds** — weather provider, Earth observation layer, agronomic data feed, custom partner feed. Partner feed authorization is required for production use.

Connected field analysis uses `POST /v1/workbench/analyze-live` with default `source: wiseconn` and `entity_id: 162803` and fails safely when credential-backed telemetry is not provisioned. Supported upload file types are CSV, JSON, TXT, and XLSX when the backend has `openpyxl` available.

Frontend data priority: backend Workbench result → live connected source → uploaded records → representative fallback values.

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

When the user runs intelligence analysis, the pipeline animates, trace steps activate, the Workbench endpoint is called, and backend `analysis_trace` data fills the **Analysis trace** panel. On success, recommendation, reconciliation, verification, and report preview sections update from the backend result. On backend failure, the UI shows: **Backend intelligence unavailable. Representative-data analysis remains available.**

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

## Tests

Dependency-free smoke tests guard the enterprise-maturity invariants (no
scaffold language, representative package auto-load, scenario switching, and
core render output):

```bash
cd customer-portal
node --test
```

## Static Deploy Note

1. Deploy `customer-portal/` as static files.
2. Keep API base set to `https://api.agroai-pilot.com` for production.
3. Do not alter Railway secrets, DNS, Cloudflare settings, or infrastructure outside explicit change control.
