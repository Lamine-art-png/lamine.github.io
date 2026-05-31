# Workbench Engine v1

Workbench Engine v1 powers the Water Command Center with real server-side parsing, schema detection, normalization, reconciliation, confidence scoring, recommendation synthesis, trace generation, and report artifact output.

## Routes

- `POST /v1/workbench/sessions`
- `POST /v1/workbench/sessions/{session_id}/upload`
- `POST /v1/workbench/sessions/{session_id}/analyze`
- `POST /v1/workbench/analyze-live`
- `POST /v1/workbench/sample-package`
- `GET /v1/workbench/sessions/{session_id}`
- `GET /v1/workbench/sessions/{session_id}/report`
- `GET /v1/workbench/schema`

## Supported File Types

- CSV
- JSON
- TXT
- XLSX when `openpyxl` is installed

Uploads are parsed in memory for v1. Permanent upload storage, credential-backed provider retrieval, and report artifact persistence are later backend work.

## Expanded Sample Data Package

`POST /v1/workbench/sample-package` creates a session with eight text-based artifacts:

- `controller_events.csv`
- `weather_summary.csv`
- `soil_moisture.csv`
- `field_notes.txt`
- `flow_meter.csv`
- `crop_profile.json`
- `water_costs.csv`
- `satellite_observation.csv`

The package covers Alpha Vineyard, Block A North, Block B West, almond blocks, vineyard blocks, planned-vs-applied variance, missing pressure cases, flow-meter variance, water cost context, and field observations. The satellite file uses the label **Earth observation sample layer** and does not claim a live EarthDaily integration.

## Analysis Output

Workbench analysis returns:

- `data_sources`: file count, rows parsed, source kinds detected, and file-level summaries.
- `normalized_context`: farm, block, crop, variety, soil, irrigation method, root-zone depth, growth stage, weather window, moisture deficit, flow variance, provider context, and field notes used.
- `signal_summary`: counts for controller events, weather records, soil readings, field notes, flow-meter records, crop profiles, earth-observation rows, and water-cost records.
- `reconciliation`: planned-vs-applied variance, controller validity, flow-meter agreement, weather demand, soil moisture deficit, field observation support, earth-observation support, missing inputs, conflicts, conflicts resolved, confidence, and evidence completeness.
- `recommendation`: action, start time, duration, depth, confidence, key drivers, limitations, and verification requirement.
- `verification_plan`: recommended chain from recommendation through verification.
- `report_summary`: water saved assumption, evidence completeness, applied variance, compliance posture, executive summary, and export rows.
- `analysis_trace`: structured trace steps for the portal Intelligence Stream.

## Analysis Trace

The trace is intentionally structured for UI animation:

1. Ingested source files
2. Detected schemas and aliases
3. Normalized units and timestamps
4. Matched farm, block, crop, and soil context
5. Reconciled controller and flow-meter evidence
6. Evaluated weather, soil deficit, and field notes
7. Calculated confidence and evidence completeness
8. Produced recommendation and verification plan

Each step includes title, status, details, objects processed, and optional confidence delta.

## Live Mode (real adapter integration)

`POST /v1/workbench/analyze-live` accepts a provider `source` and `entity_id`. The default portal call uses `source: wiseconn` and `entity_id: 162803`.

The route is now `async` and assembles live context through the existing
`LiveFieldContextAssembler` (`assemble_wiseconn_zone` / `assemble_talgil_target`)
rather than a static placeholder:

1. `engine.assemble_live_context(source, entity_id)` calls the assembler.
2. The returned `CanonicalFieldContext` is mapped onto the Workbench context
   shape (`_map_live_context`). Only telemetry the provider actually returned is
   reflected — moisture readings and recent irrigation counts when present.
   Agronomic profile fields (crop, soil) stay "provider context pending" because
   live telemetry does not carry them.
3. When provider reads are unavailable (no credentials, network, or zone match),
   the assembler degrades safely: truthful `warnings` (for example
   `wiseconn_telemetry_unavailable`, `live_context_unavailable:*`), empty
   `live_inputs_used`, and **no fabricated telemetry**. The route still returns
   `200` with a degraded-but-honest result.

Adapter logic is **not duplicated** — the route reuses the existing assembler.

## Recommendation Origin and Truthful Status Fields

Every analysis result now carries typed status fields:

- `backend_status` — `available` once the engine produced a result.
- `analysis_mode` — `live` | `uploaded` | `demo`.
- `context_origin` — `live` | `uploaded` | `representative`.
- `recommendation_origin` — one of `representative_fallback`,
  `deterministic_engine`, `live_intelligence_engine`,
  `uploaded_intelligence_engine`.
- `live_inputs_used`, `uploaded_artifacts_used`, `warnings`.

### Current recommender behavior

The Workbench recommender is **deterministic**. Above the confidence threshold
it returns a representative operational shape (42 min / 12 mm net) and below it
returns a truthful hold state: **"Decision pending source review"**. This fixed
numeric output is therefore labelled `recommendation_origin: deterministic_engine`
and must **not** be presented as calibrated agronomic precision.

The frontend labels its embedded evaluation scenarios as
`representative_fallback` and clearly marks them as representative data.

### Remaining gap (agronomic-calibration sprint)

Routing live and uploaded analysis through `IntelligenceEngineV1` to produce
calibrated numeric recommendations (which would emit `live_intelligence_engine`
/ `uploaded_intelligence_engine`) is reserved for a dedicated agronomic
calibration sprint. Until then the deterministic engine and representative
fallbacks are the source of recommendation numbers, and that origin is exposed
honestly through `recommendation_origin`.

## Current Limitations

- **Evaluation session storage only.** Sessions and artifacts are in memory;
  tenant-scoped persistence is future work. This limitation is documented here
  and is not surfaced prominently on the customer-facing Command page.
- Provider credentials must be stored server-side; browser storage is never used
  for provider secrets.
- Connected-field analysis is limited until credential vault and tenant
  provisioning are complete; live results degrade safely meanwhile.
- The recommendation numbers are deterministic, not agronomically calibrated
  (see "Remaining gap" above).
- XLSX parsing depends on `openpyxl`.
- Optional model-assisted summary requires provider environment variables;
  deterministic analysis is always available.
