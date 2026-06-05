"""Deterministic calculation engine for the FCGMA Water Intelligence Copilot.

All calculations run before the AI layer.  The AI layer may read results
but must not produce quantities beyond what this engine has calculated.

Applied-water model:
  Status: DEMO RULESET v0.1
  Purpose: Workflow demonstration
  Requires Fox Canyon validation before operational use.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .ledger import (
    CALCULATION_VERSION,
    _LEDGER,
    _EXCEPTIONS,
    add_audit_event,
    store_exception,
    upsert_record,
    list_records,
)
from .rule_pack import unit_to_af

# ─────────────────────────────────────────────
# Exception severity
# ─────────────────────────────────────────────
SEVERITY = {
    "missing_telemetry_interval": "high",
    "meter_reset_detected": "high",
    "multiplier_change": "medium",
    "unit_change": "medium",
    "duplicate_record": "high",
    "late_arriving_record": "low",
    "pump_activity_without_meter_movement": "high",
    "reverse_flow": "medium",
    "unresolved_combcode": "high",
    "unresolved_parcel_mapping": "medium",
    "backup_estimate_required": "high",
    "stale_source": "medium",
    "negative_delta": "high",
    "missing_mapping": "medium",
}

# Meter reset threshold: if cumulative drops by more than this fraction, flag as reset
METER_RESET_THRESHOLD_FRACTION = 0.10

# Stale source: if last record is older than this many hours
STALE_SOURCE_HOURS = 48


def _exc_id() -> str:
    return f"exc-{uuid.uuid4().hex[:10]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_exception(record_id: str, exc_type: str, detail: str, rule_id: str | None = None) -> dict[str, Any]:
    exc = {
        "id": _exc_id(),
        "record_id": record_id,
        "exception_type": exc_type,
        "severity": SEVERITY.get(exc_type, "medium"),
        "detail": detail,
        "rule_id": rule_id,
        "status": "open",
        "resolution": None,
        "created_at": _now(),
        "resolved_at": None,
        "resolved_by": None,
    }
    store_exception(exc)
    return {k: exc[k] for k in ("id", "exception_type", "severity", "detail", "rule_id", "status")}


# ─────────────────────────────────────────────
# Core calculations
# ─────────────────────────────────────────────

def normalize_units(record: dict[str, Any]) -> dict[str, Any]:
    """Convert cumulative_volume and interval_volume to acre-feet."""
    original_unit = record.get("unit_original") or record.get("unit", "acre-feet")
    cv = record.get("cumulative_volume")
    iv = record.get("interval_volume")

    if original_unit.lower().replace(" ", "_").replace("-", "_") != "acre_feet":
        if cv is not None:
            converted = unit_to_af(cv, original_unit)
            if converted is not None:
                record["cumulative_volume"] = converted
        if iv is not None:
            converted = unit_to_af(iv, original_unit)
            if converted is not None:
                record["interval_volume"] = converted
        record["unit"] = "acre-feet"

    return record


def apply_multiplier(record: dict[str, Any]) -> dict[str, Any]:
    """Apply meter multiplier to cumulative and interval volumes."""
    mult = record.get("multiplier", 1.0)
    if mult != 1.0:
        cv = record.get("cumulative_volume")
        iv = record.get("interval_volume")
        if cv is not None:
            record["cumulative_volume"] = round(cv * mult, 6)
        if iv is not None:
            record["interval_volume"] = round(iv * mult, 6)
    return record


def calculate_interval(record: dict[str, Any], previous_record: dict[str, Any] | None) -> dict[str, Any]:
    """Calculate interval volume from cumulative delta if interval not already set."""
    if record.get("interval_volume") is not None:
        return record
    if previous_record is None:
        return record

    cv = record.get("cumulative_volume")
    prev_cv = previous_record.get("cumulative_volume")
    if cv is None or prev_cv is None:
        return record

    delta = cv - prev_cv
    record["interval_volume"] = round(delta, 6)
    return record


def detect_negative_delta(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Detect negative interval volume (possible meter reset or reverse flow)."""
    iv = record.get("interval_volume")
    if iv is not None and iv < -0.0001:
        return [_make_exception(
            record["id"],
            "negative_delta",
            f"Negative interval volume: {iv:.4f} AF. Possible meter reset or reverse flow. "
            "Requires review before extraction calculation.",
            rule_id="fcgma-fm-004",
        )]
    return []


def detect_meter_reset(record: dict[str, Any], previous_record: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Detect meter reset: cumulative drops significantly from previous reading."""
    if previous_record is None:
        return []
    cv = record.get("cumulative_volume")
    prev_cv = previous_record.get("cumulative_volume")
    if cv is None or prev_cv is None or prev_cv == 0:
        return []
    if cv < prev_cv and (prev_cv - cv) / prev_cv > METER_RESET_THRESHOLD_FRACTION:
        return [_make_exception(
            record["id"],
            "meter_reset_detected",
            f"Cumulative volume dropped from {prev_cv:.4f} to {cv:.4f} AF "
            f"({((prev_cv - cv) / prev_cv * 100):.1f}% drop). "
            "Likely meter reset. Agency notification required per FCGMA rule fcgma-fm-004.",
            rule_id="fcgma-fm-004",
        )]
    return []


def detect_duplicate(record: dict[str, Any], all_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect duplicate records: same meter, same timestamp, same provider."""
    excs = []
    for r in all_records:
        if (
            r["id"] != record["id"]
            and r["meter_id"] == record["meter_id"]
            and r["event_timestamp"] == record["event_timestamp"]
            and r["provider"] == record["provider"]
        ):
            excs.append(_make_exception(
                record["id"],
                "duplicate_record",
                f"Record {record['id']} appears to duplicate {r['id']} "
                f"(meter {record['meter_id']}, timestamp {record['event_timestamp']}). "
                "Only one record should contribute to extraction totals.",
            ))
    return excs


def detect_unresolved_combcode(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag records without a CombCode mapping."""
    if record.get("evidence_class") == "groundwater_meter_reading" and not record.get("combcode"):
        return [_make_exception(
            record["id"],
            "unresolved_combcode",
            "No CombCode mapping for this groundwater meter record. "
            "CombCode is required to link extraction to the correct management zone. "
            "Contact FCGMA to obtain the correct CombCode for this well.",
            rule_id="fcgma-gis-001",
        )]
    return []


def detect_unresolved_parcel_mapping(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag records without parcel mapping."""
    if record.get("evidence_class") == "groundwater_meter_reading" and not record.get("parcel_ids"):
        return [_make_exception(
            record["id"],
            "unresolved_parcel_mapping",
            "No parcel mapping for this groundwater meter record. "
            "Parcel association is required for applied-water attribution. "
            "Confirm well-to-parcel mapping with the operator.",
            rule_id="fcgma-aw-001",
        )]
    return []


def detect_missing_interval(
    record: dict[str, Any],
    previous_record: dict[str, Any] | None,
    max_gap_hours: float = 26.0,
) -> list[dict[str, Any]]:
    """Detect unexpectedly large time gaps between consecutive records."""
    if previous_record is None:
        return []
    try:
        t1 = datetime.fromisoformat(previous_record["event_timestamp"].replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(record["event_timestamp"].replace("Z", "+00:00"))
        gap_hours = (t2 - t1).total_seconds() / 3600
        if gap_hours > max_gap_hours:
            return [_make_exception(
                record["id"],
                "missing_telemetry_interval",
                f"Gap of {gap_hours:.1f} hours between meter readings "
                f"({previous_record['event_timestamp']} to {record['event_timestamp']}). "
                "Expected maximum gap is 24 hours. Possible data transmission failure.",
                rule_id="fcgma-fm-001",
            )]
    except (ValueError, KeyError):
        pass
    return []


def detect_pump_without_meter(
    pump_records: list[dict[str, Any]],
    meter_records: list[dict[str, Any]],
    tolerance_af: float = 0.001,
) -> list[dict[str, Any]]:
    """Flag pump activity that has no corresponding meter volume movement."""
    new_exceptions = []
    for pr in pump_records:
        if pr.get("pump_status") not in ("running", "on", "active"):
            continue
        ts = pr.get("event_timestamp", "")
        well = pr.get("well_id", "")
        matching_meter = [
            m for m in meter_records
            if m.get("well_id") == well
            and m.get("event_timestamp", "")[:13] == ts[:13]
            and (m.get("interval_volume") or 0) > tolerance_af
        ]
        if not matching_meter:
            new_exceptions.append(_make_exception(
                pr["id"],
                "pump_activity_without_meter_movement",
                f"Pump status 'active' recorded at {ts} for well {well} "
                "but no corresponding meter volume movement found in that hour. "
                "Possible meter malfunction, data gap, or unmetered extraction.",
                rule_id="fcgma-fm-001",
            ))
    return new_exceptions


def detect_backup_estimate_required(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag records that require backup estimation due to missing meter data."""
    flags = record.get("source_quality", "ok")
    if flags in ("meter_failure", "data_gap", "unreliable"):
        return [_make_exception(
            record["id"],
            "backup_estimate_required",
            f"Source quality flagged as '{flags}'. A backup estimate is required "
            "per FCGMA meter failure workflow. The backup method must be pre-approved "
            "by FCGMA. Estimated volumes are provisional.",
            rule_id="fcgma-fm-003",
        )]
    return []


def compute_provisional_attribution(record: dict[str, Any]) -> dict[str, Any]:
    """
    Compute provisional applied-water attribution where evidence supports it.

    Applied-water model: DEMO RULESET v0.1
    Status: Provisional
    Purpose: Workflow demonstration
    Requires Fox Canyon validation.

    Attribution is provisional when:
    - CombCode is unresolved, OR
    - Parcel mapping is incomplete, OR
    - Multiplier has changed, OR
    - Record has open exceptions
    """
    iv = record.get("interval_volume")
    if iv is None or iv <= 0:
        return record

    open_exceptions = [e for e in record.get("exceptions", []) if e.get("status") != "resolved"]
    combcode_ok = bool(record.get("combcode"))
    parcel_ok = bool(record.get("parcel_ids"))

    provisional = (
        not combcode_ok
        or not parcel_ok
        or len(open_exceptions) > 0
        or record.get("source_quality") not in ("ok", None)
    )

    record["provisional_applied_water_af"] = iv if provisional else None
    record["confirmed_applied_water_af"] = iv if not provisional else None
    record["attribution_provisional"] = provisional
    record["attribution_model"] = "DEMO RULESET v0.1"
    record["attribution_model_status"] = "provisional"
    record["attribution_requires_validation"] = True
    record["attribution_caveats"] = [
        "Applied-water model is a demonstration ruleset only.",
        "Requires Fox Canyon Groundwater Management Agency validation.",
        "CombCode and parcel mapping must be confirmed.",
        "Multiplier and unit history must be verified.",
    ]

    return record


def recompute_record(record_id: str) -> dict[str, Any] | None:
    """Recompute a single record: normalize, apply multiplier, detect exceptions."""
    r = _LEDGER.get(record_id)
    if not r:
        return None

    # Clear existing auto-detected exceptions (keep manual reviewer ones)
    r["exceptions"] = [
        e for e in r["exceptions"]
        if e.get("exception_type") in ("reviewer_adjustment",)
    ]

    # Find previous record for same meter (sorted by timestamp)
    same_meter = sorted(
        [x for x in _LEDGER.values()
         if x["meter_id"] == r["meter_id"] and x["id"] != r["id"]],
        key=lambda x: x["event_timestamp"],
    )
    prev = None
    for candidate in same_meter:
        if candidate["event_timestamp"] < r["event_timestamp"]:
            prev = candidate
        else:
            break

    all_records = list(_LEDGER.values())

    r = normalize_units(r)
    r = apply_multiplier(r)
    r = calculate_interval(r, prev)

    new_excs: list[dict[str, Any]] = []
    new_excs += detect_negative_delta(r)
    new_excs += detect_meter_reset(r, prev)
    new_excs += detect_duplicate(r, all_records)
    new_excs += detect_missing_interval(r, prev)
    new_excs += detect_unresolved_combcode(r)
    new_excs += detect_unresolved_parcel_mapping(r)
    new_excs += detect_backup_estimate_required(r)

    r["exceptions"].extend(new_excs)

    # Update review status based on exceptions
    open_excs = [e for e in r["exceptions"] if e.get("status") != "resolved"]
    if open_excs:
        r["review_status"] = "requires_attention"
    elif r["review_status"] == "pending_review":
        r["review_status"] = "ready_for_export"

    r = compute_provisional_attribution(r)
    r["calculation_version"] = CALCULATION_VERSION
    r["updated_at"] = _now()

    r["audit_events"].append({
        "event_type": "recomputed",
        "timestamp": _now(),
        "actor": "calculation_engine",
        "detail": f"Recomputed with {CALCULATION_VERSION}. Exceptions: {len(new_excs)}",
    })

    upsert_record(r)
    return r


def run_full_calculation_pass() -> dict[str, Any]:
    """Run calculation engine over all ledger records. Returns summary."""
    record_ids = list(_LEDGER.keys())
    processed = 0
    exceptions_raised = 0

    for record_id in record_ids:
        result = recompute_record(record_id)
        if result:
            processed += 1
            exceptions_raised += len(result.get("exceptions", []))

    pump_records = [r for r in _LEDGER.values() if r.get("evidence_class") == "pump_state_evidence"]
    meter_records = [r for r in _LEDGER.values() if r.get("evidence_class") == "groundwater_meter_reading"]
    pump_excs = detect_pump_without_meter(pump_records, meter_records)
    exceptions_raised += len(pump_excs)

    return {
        "calculation_version": CALCULATION_VERSION,
        "records_processed": processed,
        "exceptions_raised": exceptions_raised,
        "timestamp": _now(),
        "applied_water_model": "DEMO RULESET v0.1",
        "applied_water_model_status": "provisional",
        "applied_water_requires_validation": True,
    }


def get_calculation_explanation(record: dict[str, Any]) -> dict[str, Any]:
    """Return a human-readable explanation of how a record was calculated."""
    steps = []

    orig_unit = record.get("unit_original", "acre-feet")
    if orig_unit != "acre-feet":
        steps.append({
            "step": "unit_normalization",
            "description": f"Original unit '{orig_unit}' converted to acre-feet using standard conversion factor.",
            "rule_id": None,
        })

    mult = record.get("multiplier", 1.0)
    if mult != 1.0:
        steps.append({
            "step": "multiplier_applied",
            "description": f"Meter multiplier {mult} applied to cumulative and interval volumes.",
            "rule_id": "fcgma-fm-004",
        })

    cv = record.get("cumulative_volume")
    iv = record.get("interval_volume")
    if cv is not None and iv is not None:
        steps.append({
            "step": "interval_calculated",
            "description": (
                f"Interval volume {iv:.4f} AF calculated as cumulative delta. "
                "This represents extraction during the reporting interval only."
            ),
            "rule_id": None,
        })

    attribution = record.get("attribution_provisional")
    if attribution is not None:
        status = "provisional" if attribution else "supported"
        steps.append({
            "step": "applied_water_attribution",
            "description": (
                f"Applied-water attribution is {status}. "
                "Model: DEMO RULESET v0.1 — requires Fox Canyon validation."
            ),
            "rule_id": "fcgma-aw-001",
        })

    excs = record.get("exceptions", [])
    if excs:
        steps.append({
            "step": "exceptions_detected",
            "description": (
                f"{len(excs)} exception(s) detected: "
                + ", ".join(e["exception_type"] for e in excs)
                + ". Review required before record can be included in export."
            ),
            "rule_id": None,
        })

    return {
        "record_id": record["id"],
        "calculation_version": CALCULATION_VERSION,
        "steps": steps,
        "model_disclaimer": (
            "Applied-water model: DEMO RULESET v0.1 | Status: Provisional | "
            "Purpose: Workflow demonstration | Requires Fox Canyon validation"
        ),
        "rule_sources": [
            "https://fcgma.org/flowmeter-requirements/",
            "https://fcgma.org/agency-forms/",
        ],
    }
