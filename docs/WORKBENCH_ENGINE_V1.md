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
- `POST /v1/workbench/sessions/{session_id}/actions/schedule`
- `POST /v1/workbench/sessions/{session_id}/actions/applied`
- `POST /v1/workbench/sessions/{session_id}/actions/observe`
- `POST /v1/workbench/sessions/{session_id}/actions/verify`
- `GET /v1/workbench/sessions/{session_id}/evidence-chain`
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
- `recommendation`: action, start time, net depth, gross depth, estimated
  volume, duration only when flow evidence exists, confidence, key drivers,
  assumptions, limitations, missing inputs, calculation trace, calibration
  status, calibration-pack version, recommendation origin, and verification
  requirement.
- `verification_plan`: recommended chain from recommendation through verification.
- `report_summary`: water saved assumption, evidence completeness, applied variance, compliance posture, executive summary, and export rows.
- `analysis_trace`: structured trace steps for the portal Intelligence Stream.

## Analysis Trace

The trace is intentionally structured for UI animation:

1. Source records ingested
2. Schema detected
3. Units normalized
4. Field context assembled
5. Source conflicts reconciled
6. Confidence scored
7. Recommendation prepared
8. Verification plan prepared

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

The Workbench recommender now routes uploaded and live analysis through the v0.2
irrigation decision orchestrator. The orchestrator normalizes context through
`IntelligenceEngineV1`, scores missing inputs, resolves transparent calibration
defaults, and calls the deterministic agronomic decision kernel.

The kernel uses conservative formulas:

- crop demand = ETo * crop coefficient
- net irrigation need = crop demand - effective rainfall + validated root-zone
  replenishment need - recent verified irrigation credit
- gross irrigation need = net irrigation need / irrigation efficiency
- required volume = gross irrigation need * field area
- duration = required volume / validated system flow

Duration is omitted unless validated flow or controller capacity evidence
exists. Incomplete live context therefore returns `Inspect and collect required
evidence` or `Decision pending source review` rather than fabricated precision.

`recommendation_origin` is `live_intelligence_engine` for live requests and
`uploaded_intelligence_engine` for uploaded/session analysis. Representative UI
scenarios remain labelled `representative_fallback`.

## Evidence Chain Evaluation Persistence

The action routes record schedule approval, applied-water confirmation, field
observation, and outcome verification in the existing in-memory evaluation
session store. Responses include action status, timestamp, actor, evidence
summary, updated evidence chain, and audit event.

This is explicitly **evaluation-session persistence only**. It is not durable
tenant persistence and must not be described as production audit storage.

## Current Limitations

- **Evaluation session storage only.** Sessions and artifacts are in memory;
  tenant-scoped persistence is future work. This limitation is documented here
  and is not surfaced prominently on the customer-facing Command page.
- Provider credentials must be stored server-side; browser storage is never used
  for provider secrets.
- Connected-field analysis is limited until credential vault and tenant
  provisioning are complete; live results degrade safely meanwhile.
- v0.2 calibration defaults are transparent defaults, not farm-specific
  calibration. Farm-specific crop coefficients, soil curves, flow validation,
  and controller application rates are production follow-ups.
- XLSX parsing depends on `openpyxl`.
- Optional model-assisted summary requires provider environment variables;
  deterministic analysis is always available.
