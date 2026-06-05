# AGRO-AI Water Intelligence Copilot — Fox Canyon Applied-Water Mission Control

**Version:** 0.1.0  
**Status:** First production-shaped vertical slice  
**Updated:** 2026-06-05

---

## Overview

The FCGMA Water Intelligence Copilot is a serious institutional AI product designed to demonstrate how AGRO-AI can:

1. Ingest authorized real-world telemetry from existing providers
2. Normalize fragmented records into a vendor-neutral water ledger
3. Distinguish controller telemetry, groundwater meter records, pump-state evidence, weather context, and provisional applied-water attribution
4. Calculate only what deterministic evidence and configured rules support
5. Detect exceptions and missing evidence
6. Explain each output with visible source lineage
7. Answer operational questions live through a grounded AI copilot
8. Generate polished reporting-ready outputs (PDF, CSV, audit bundle)
9. Remain honest about what is live, what is public contextual data, what is provisional, and what is demonstration scenario

---

## Architecture

### Backend (`agroai_api/app/`)

```
app/
  api/v1/fcgma_demo.py          — All API routes under /v1/fcgma-demo/
  services/fcgma/
    __init__.py
    rule_pack.py                 — Fox Canyon public-context rule pack (v0.1)
    ledger.py                    — Canonical in-memory water ledger + CRUD
    calculation_engine.py        — Deterministic calculation engine
    scenarios.py                 — Demo scenario injection (16 scenarios)
    cimis_adapter.py             — CIMIS live weather adapter
    copilot.py                   — Grounded AI copilot with deterministic fallback
    reports.py                   — PDF/CSV/JSON/ZIP report generation
```

### Frontend (`customer-portal/`)

```
customer-portal/
  fcgma-demo.html               — Standalone executive UI (no build step required)
```

### Tests (`agroai_api/tests/`)

```
tests/
  test_fcgma_demo.py            — 65 tests covering all required scenarios
```

### Documentation (`docs/`)

```
docs/
  fcgma-water-intelligence-copilot.md   — Architecture (this file)
  fcgma-data-truthfulness.md            — Truthfulness contract
  fcgma-demo-runbook.md                 — Demo and operation guide
```

---

## API Endpoints

All endpoints are under `/v1/fcgma-demo/`.

| Method | Path | Description |
|---|---|---|
| GET | `/status` | Environment, provider health, ledger stats |
| GET | `/dashboard` | Executive summary, metrics, recent exceptions |
| GET | `/source-health` | Provider health + rule pack metadata |
| GET | `/review-queue` | Priority review queue with filters |
| GET | `/records/{id}` | Full record detail |
| GET | `/records/{id}/ledger` | Ledger view with calculation explanation |
| GET | `/records/{id}/audit` | Audit events and exceptions |
| POST | `/records/{id}/recompute` | Recompute calculation for a record |
| PATCH | `/records/{id}/review` | Update review status |
| GET | `/exceptions` | All open exceptions |
| POST | `/exceptions/{id}/resolve` | Resolve an exception |
| POST | `/imports/ami-csv` | Import AMI CSV file |
| POST | `/scenarios/reset` | Reset to standard demo dataset |
| POST | `/scenarios/inject` | Inject demo scenarios |
| POST | `/copilot/query` | Ask AGRO-AI copilot |
| GET | `/copilot/preset-questions` | Available preset questions |
| GET | `/weather/cimis` | CIMIS live weather (requires CIMIS_APP_KEY) |
| GET | `/rules` | Fox Canyon rule pack |
| POST | `/reports/generate` | Generate full report bundle |
| GET | `/reports/{id}` | Report metadata |
| GET | `/reports/{id}/pdf` | Download executive PDF |
| GET | `/reports/{id}/csv` | Download records or exceptions CSV |
| GET | `/reports/{id}/bundle` | Download ZIP bundle |

---

## Provider Registry

| Provider ID | Status | Evidence Class | Notes |
|---|---|---|---|
| `wiseconn_authorized_live` | Enabled (requires key) | `controller_irrigation_telemetry` | Controller telemetry only — no extraction volumes |
| `wiseconn_sanitized_replay` | Enabled | `controller_irrigation_telemetry` | Anonymized replay captures |
| `fcgma_generic_ami_csv` | Enabled | `groundwater_meter_reading` | Generic AMI import |
| `cimis_live_weather` | Enabled (requires key) | `weather_context` | Weather context only |
| `public_fcgma_context` | Enabled | `public_context` | Public documents |
| `ranch_systems_adapter_pending` | **Disabled** | None | Awaiting official schema/authorization |

---

## Calculation Engine

The deterministic engine runs before the AI layer. It performs:

1. Unit normalization (gallons/cubic-feet → acre-feet)
2. Multiplier application
3. Cumulative delta calculation
4. Negative delta detection
5. Meter reset detection
6. Duplicate detection
7. Missing interval detection
8. CombCode validation
9. Parcel mapping validation
10. Backup estimation detection
11. Pump-without-meter detection
12. Provisional applied-water attribution

Applied-water model: **DEMO RULESET v0.1** — Provisional — Requires Fox Canyon validation.

---

## Demonstration Scenarios

16 scenarios are injected on first use (or on reset):

1. Clean record (baseline)
2. Missing telemetry interval (38-hour gap)
3. Meter reset (cumulative drop from 9,850 to 12 AF)
4. Multiplier change
5. Unit change (gallons to AF)
6. Duplicate records (same timestamp, same meter)
7. Late-arriving record (45 days late, prior period)
8. Pump activity without meter movement
9. Reverse flow (negative interval)
10. Unresolved CombCode
11. Unresolved parcel mapping
12. One well — multiple parcels
13. Multiple wells — one parcel
14. Meter failure requiring backup estimation
15. Reviewer adjustment
16. WiseConn controller telemetry (sanitized replay)

---

## Copilot Tools

The copilot dispatches to these deterministic tools:

| Tool | What It Does |
|---|---|
| `get_executive_summary` | Narrative + stats from ledger |
| `list_records_requiring_attention` | Records with open exceptions |
| `explain_record(id)` | Full explanation with calculation steps |
| `get_water_ledger(id)` | Complete ledger view |
| `compare_provider_health` | All providers status |
| `show_data_lineage(id)` | Source lineage and audit events |
| `list_unvalidated_assumptions` | Gap analysis |
| `run_applied_water_scenario` | Attribution scenario results |
| `generate_reporting_summary` | Reporting readiness summary |
| `generate_exception_report` | All open exceptions |
| `draft_operator_follow_up` | Follow-up actions per exception |

---

## Known Limitations

1. Ledger is in-memory — restarts clear the state (appropriate for demo; production would use the existing database)
2. WiseConn live adapter provides controller telemetry only — not groundwater extraction records
3. No authorized Fox Canyon extraction data is included anywhere in this version
4. Ranch Systems adapter is intentionally disabled — no schema or authorization exists
5. Applied-water model is a demo ruleset — not validated regulatory logic
6. CIMIS requires a separate API key registration
7. Report PDF uses basic reportlab layout — production would benefit from a more polished template
8. The demo portal HTML is a single-file implementation — production would use the full portal build pipeline

---

## Highest-Priority Next Review Items

1. **Fox Canyon validation**: Request CombCode mapping, official attribution methodology, and backup estimation procedure
2. **Ranch Systems schema**: Request official export format to enable the disabled adapter
3. **Live AMI feed**: Connect to Fox Canyon's actual AMI data feed when authorized
4. **Rule pack validation**: Have Fox Canyon staff validate every rule in `rule_pack.py`
5. **Database persistence**: Move in-memory ledger to the existing SQLAlchemy database for production
6. **Authentication**: Add operator-level authentication to review and adjustment endpoints
