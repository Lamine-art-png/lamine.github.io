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

## Live Mode

`POST /v1/workbench/analyze-live` accepts a provider source and entity id. The default portal call uses `source: wiseconn` and `entity_id: 162803`. The route returns a customer-safe limited analysis when provider credential provisioning is not available. It does not fabricate live telemetry.

## Current Limitations

- Sessions and artifacts are in memory.
- Provider credentials must be stored server-side; browser storage is not used for provider secrets.
- Connected field analysis is limited until credential vault and tenant provisioning are complete.
- XLSX parsing depends on `openpyxl`.
- Optional model-assisted summary requires provider environment variables; deterministic analysis is always available.
