"""ReviewCase model for the FCGMA Water Intelligence Copilot.

Groups related exceptions by well and reporting period into coherent
review cases that an operator or reviewer can act on as a unit.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .ledger import list_exceptions, list_records, CALCULATION_VERSION
from .copilot import _recommend_action


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Exception types that constitute a "material" case (high/medium severity)
_MATERIAL_TYPES = {
    "meter_reset_detected",
    "missing_telemetry_interval",
    "pump_activity_without_meter_movement",
    "backup_estimate_required",
    "unresolved_combcode",
    "duplicate_record",
    "multiplier_change",
    "unit_change",
    "reverse_flow",
    "negative_delta",
    "late_arriving_record",
}

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _case_title(exc_types: list[str], well_id: str) -> str:
    primary = exc_types[0] if exc_types else "unknown"
    labels = {
        "meter_reset_detected": "Meter Reset",
        "missing_telemetry_interval": "Telemetry Gap",
        "pump_activity_without_meter_movement": "Pump Activity Without Meter Movement",
        "backup_estimate_required": "Backup Estimate Required",
        "unresolved_combcode": "Unresolved CombCode",
        "duplicate_record": "Duplicate Record",
        "multiplier_change": "Multiplier Change",
        "unit_change": "Unit Change",
        "reverse_flow": "Reverse Flow Detected",
        "negative_delta": "Negative Delta",
        "late_arriving_record": "Late-Arriving Record",
    }
    label = labels.get(primary, primary.replace("_", " ").title())
    return f"{label} — {well_id}"


def _why_it_matters(exc_types: list[str], affected_af: float) -> str:
    primary = exc_types[0] if exc_types else ""
    qty = f"{affected_af:.2f} AF" if affected_af > 0 else "an unknown quantity"
    messages = {
        "meter_reset_detected": (
            f"A suspected meter replacement introduced a large negative cumulative delta. "
            f"Without resolution, {qty} of extraction cannot be attributed to the correct reporting period. "
            "FCGMA requires agency notification and documentation of the new meter serial number."
        ),
        "missing_telemetry_interval": (
            f"A {qty}-period data gap occurred during confirmed pump activity. "
            "Extraction may have occurred and gone unrecorded. "
            "A backup estimate may be required if the gap cannot be explained."
        ),
        "pump_activity_without_meter_movement": (
            "Pump was active with no corresponding meter volume. "
            "This suggests a meter malfunction or unmetered extraction. "
            "FCGMA may require a backup estimate or field inspection."
        ),
        "backup_estimate_required": (
            f"Meter failure prevented reading during an active extraction period. "
            f"{qty} is unaccounted. An FCGMA-pre-approved backup estimate is required."
        ),
        "unresolved_combcode": (
            f"{qty} cannot be attributed to a management zone without a confirmed CombCode. "
            "Records with unresolved CombCodes cannot be included in a reporting-ready export."
        ),
        "multiplier_change": (
            f"A multiplier change affects how raw meter readings are converted to AF. "
            f"If the change is unverified, {qty} may be over- or under-reported."
        ),
    }
    return messages.get(primary, (
        f"This exception affects {qty} and requires resolution before the record "
        "can be included in the reporting export."
    ))


def _primary_issue(exc_types: list[str]) -> str:
    labels = {
        "meter_reset_detected": "Meter replacement — cumulative reset not yet documented",
        "missing_telemetry_interval": "Data gap during active pump period",
        "pump_activity_without_meter_movement": "Pump active with no meter volume",
        "backup_estimate_required": "Meter failure — reading unavailable",
        "unresolved_combcode": "CombCode not resolved — management zone unknown",
        "duplicate_record": "Duplicate submission detected",
        "multiplier_change": "Meter multiplier changed — requires agency notification",
        "unit_change": "Unit of measure changed — conversion must be verified",
        "reverse_flow": "Negative interval detected — possible reverse flow or data error",
        "negative_delta": "Negative cumulative delta quarantined",
        "late_arriving_record": "Record arrived after reporting period closed",
    }
    primary = exc_types[0] if exc_types else ""
    return labels.get(primary, f"Exception: {primary.replace('_', ' ')}")


def _required_evidence(exc_types: list[str]) -> list[str]:
    ev = {
        "meter_reset_detected": [
            "Previous meter serial number and final reading",
            "New meter serial number, model, and installation date",
            "FCGMA meter change notification form",
        ],
        "missing_telemetry_interval": [
            "Explanation of data transmission failure or system outage",
            "Pump run records for the gap period",
            "Backup estimate if extraction occurred (FCGMA pre-approved method)",
        ],
        "pump_activity_without_meter_movement": [
            "Field inspection report for the meter",
            "Confirmation of pump run duration and rate",
            "Backup estimate if meter was malfunctioning (FCGMA pre-approved method)",
        ],
        "backup_estimate_required": [
            "FCGMA-pre-approved backup estimation procedure",
            "Supporting evidence for estimated volume",
            "Documentation of meter failure period",
        ],
        "unresolved_combcode": [
            "Official CombCode from FCGMA for this well",
            "Well registration confirmation",
        ],
        "multiplier_change": [
            "Documentation of meter multiplier change",
            "FCGMA agency notification form",
            "Effective date of multiplier change",
        ],
    }
    result = []
    for t in exc_types:
        result.extend(ev.get(t, [f"Documentation for {t.replace('_', ' ')}"]))
    return list(dict.fromkeys(result))  # deduplicate, preserve order


def build_cases(reporting_period: str | None = None) -> list[dict[str, Any]]:
    """Group open exceptions by (well_id, reporting_period) into ReviewCases.

    Returns a list of ReviewCase dicts, sorted by severity then exception count.
    """
    exceptions = list_exceptions()
    records = list_records(reporting_period=reporting_period)

    # Build record lookup
    rec_by_id: dict[str, dict] = {r["id"]: r for r in records}

    # Also include all records (not just filtered by period) for cross-period lookup
    all_records = list_records()
    all_rec_by_id: dict[str, dict] = {r["id"]: r for r in all_records}

    # Group open exceptions by (well_id, reporting_period)
    groups: dict[tuple[str, str], list[dict]] = {}
    for exc in exceptions:
        if exc.get("status") == "resolved":
            continue
        rec = all_rec_by_id.get(exc.get("record_id", ""))
        if not rec:
            continue
        if reporting_period and rec.get("reporting_period") != reporting_period:
            continue
        key = (rec["well_id"], rec["reporting_period"])
        groups.setdefault(key, []).append(exc)

    cases: list[dict[str, Any]] = []
    for (well_id, period), excs in groups.items():
        # Collect affected record IDs
        record_ids = list(dict.fromkeys(e["record_id"] for e in excs if e.get("record_id")))
        # Deduplicate exception types
        exc_types_ordered: list[str] = []
        seen: set[str] = set()
        for e in sorted(excs, key=lambda x: _SEVERITY_RANK.get(x.get("severity", "low"), 2)):
            t = e["exception_type"]
            if t not in seen:
                exc_types_ordered.append(t)
                seen.add(t)

        # Compute affected quantity (sum of positive interval volumes from affected records)
        affected_af = 0.0
        for rid in record_ids:
            r = all_rec_by_id.get(rid, {})
            iv = r.get("interval_volume") or 0
            if iv > 0:
                affected_af += iv

        # Primary severity
        severity_ranks = [_SEVERITY_RANK.get(e.get("severity", "low"), 2) for e in excs]
        primary_severity = ["high", "medium", "low"][min(severity_ranks)]

        case_id = f"case-{well_id.lower().replace('-', '')}-{period.replace('-', '').lower()}"

        cases.append({
            "case_id": case_id,
            "title": _case_title(exc_types_ordered, well_id),
            "well_id": well_id,
            "reporting_period": period,
            "record_ids": record_ids,
            "severity": primary_severity,
            "status": "open",
            "issue_categories": exc_types_ordered,
            "primary_issue": _primary_issue(exc_types_ordered),
            "affected_quantity_af": round(affected_af, 4),
            "evidence_count": len(excs),
            "why_it_matters": _why_it_matters(exc_types_ordered, affected_af),
            "recommended_action": _recommend_action(exc_types_ordered[0]) if exc_types_ordered else "",
            "required_evidence": _required_evidence(exc_types_ordered),
            "resolution_history": [],
            "provenance": {
                "calculation_version": CALCULATION_VERSION,
                "generated_at": _now(),
                "source": "deterministic_exception_grouping",
            },
        })

    # Sort by severity then evidence count
    cases.sort(key=lambda c: (_SEVERITY_RANK.get(c["severity"], 2), -c["evidence_count"]))
    return cases
