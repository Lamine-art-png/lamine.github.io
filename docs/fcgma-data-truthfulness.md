# FCGMA Water Intelligence Copilot — Data Truthfulness Contract

**Version:** 0.1.0  
**Status:** Active — non-negotiable constraints  
**Updated:** 2026-06-05

---

## Core Principle

Every output from the FCGMA Water Intelligence Copilot must be truthful about the origin, class, confidence, and limitations of every piece of data it presents. This document is the authoritative reference for what is and is not claimed.

---

## What Is Live

| Source | Status | Notes |
|---|---|---|
| WiseConn controller telemetry | Live when `WISECONN_API_KEY` is set | Controller telemetry only. Does NOT represent groundwater extraction volumes. |
| CIMIS weather context | Live when `CIMIS_APP_KEY` is set | Reference ET context. Does not alter meter calculations. |

## What Is Public Contextual Data

| Source | What It Is | What It Is NOT |
|---|---|---|
| FCGMA public website | Public documents: flowmeter requirements, agency forms, GIS map | Official Fox Canyon data feed, internal records, regulatory submissions |
| FCGMA Resolution 2018-01 | Public AMI requirement resolution | Internal implementation rules |
| CIMIS ET data | Public weather reference data | Extraction records |

## What Is Sanitized Replay

| Source | Status |
|---|---|
| WiseConn sanitized replay | Captures from authorized WiseConn access. Customer names, farm names, exact addresses, and sensitive identifiers replaced with anonymized IDs. Provenance documented per record. |

## What Is Injected Scenario Data

All demonstration scenario records carry:
- `scenario_injected: true`
- `scenario_label: "Demonstration scenario injected to illustrate exception handling."`
- `evidence_class: "injected_demo_scenario"` or the applicable class

These records are **never mixed silently** with live or authorized records.

---

## Evidence Classes (Non-Negotiable)

| Class | What It Means |
|---|---|
| `controller_irrigation_telemetry` | WiseConn or similar controller data. Represents irrigation schedule events. **Does NOT represent groundwater extraction volumes.** |
| `groundwater_meter_reading` | AMI or manual meter reading. May represent extraction. Must have CombCode and parcel mapping confirmed before use in reports. |
| `pump_state_evidence` | Pump on/off state. May indicate extraction activity but is NOT a volume measurement. |
| `weather_context` | CIMIS ETo, precipitation, temperature. Contextual only. **Must not alter meter calculations.** |
| `public_context` | FCGMA public documents. Reference only. |
| `provisional_applied_water_attribution` | Applied-water calculation that remains provisional pending validation. |
| `reviewer_adjustment` | Manual adjustment by an authorized reviewer. Must have audit event. |
| `injected_demo_scenario` | Explicitly injected demonstration data. |

---

## What Is NEVER Claimed

1. No record is labeled as Fox Canyon production data unless it actually came from Fox Canyon under authorization.
2. No Ranch Systems integration exists or is implied. The adapter is explicitly disabled.
3. No groundwater extraction is calculated from controller telemetry alone.
4. No records are fabricated from guessed API schemas.
5. The AI copilot does not approve records, file regulatory reports, or claim legal compliance.
6. The applied-water model (DEMO RULESET v0.1) is not presented as validated regulatory logic.
7. CIMIS weather data does not silently alter extraction calculations.

---

## Applied-Water Attribution Disclaimer

Applied-water model: **DEMO RULESET v0.1**

| Field | Value |
|---|---|
| Status | Provisional |
| Purpose | Workflow demonstration only |
| Validation | Requires Fox Canyon Groundwater Management Agency validation |
| Rule sources | Public FCGMA documents only |

Attribution is provisional when:
- CombCode is unresolved
- Parcel mapping is incomplete
- Open exceptions exist
- Source quality is not `ok`

---

## Truthfulness Enforcement Points

1. **UI**: Prominent banner on every page load.
2. **API**: `truthfulness_statement` in `/v1/fcgma-demo/status` response.
3. **Every record**: `scenario_injected` flag and `scenario_label`.
4. **Every calculation**: `calculation_version`, `attribution_model_status`, `attribution_requires_validation`.
5. **Every report**: Prominent DEMONSTRATION disclaimer on every page.
6. **AI copilot**: Grounded in deterministic tools. Must not generate unsupported quantities.
7. **Provider registry**: `ranch_systems_adapter_pending` explicitly disabled with clear note.
