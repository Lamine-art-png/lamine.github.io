"""Normalized water ledger — canonical in-memory store for FCGMA demo.

All records in this ledger carry an evidence_class, source_lineage, and
scenario_injected flag.  The store is intentionally in-memory for the demo;
a production deployment would persist to the existing database.
"""
from __future__ import annotations

import hashlib
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

# ─────────────────────────────────────────────
# Evidence classes (non-negotiable)
# ─────────────────────────────────────────────
EVIDENCE_CLASSES = {
    "controller_irrigation_telemetry",
    "groundwater_meter_reading",
    "pump_state_evidence",
    "weather_context",
    "public_context",
    "provisional_applied_water_attribution",
    "reviewer_adjustment",
    "injected_demo_scenario",
}

# Provider registry entries
PROVIDER_REGISTRY: dict[str, dict[str, Any]] = {
    "wiseconn_authorized_live": {
        "label": "WiseConn (Authorized Live)",
        "status": "enabled",
        "description": "Authorized WiseConn runtime access via existing AGRO-AI integration.",
        "requires_env": ["WISECONN_API_KEY"],
        "evidence_class": "controller_irrigation_telemetry",
        "note": "Provides controller telemetry only. Does NOT produce groundwater extraction records.",
    },
    "wiseconn_sanitized_replay": {
        "label": "WiseConn (Sanitized Replay)",
        "status": "enabled",
        "description": "Sanitized replay captures from authorized WiseConn runtime. Customer identifiers replaced with anonymized IDs.",
        "requires_env": [],
        "evidence_class": "controller_irrigation_telemetry",
        "note": "Replay records are derived from authorized captures. Provenance documented per record.",
    },
    "fcgma_generic_ami_csv": {
        "label": "FCGMA Generic AMI CSV Import",
        "status": "enabled",
        "description": "Generic AMI meter CSV import. Format must conform to the FCGMA import template.",
        "requires_env": [],
        "evidence_class": "groundwater_meter_reading",
        "note": "Imported records remain provisional until CombCode and parcel mapping are validated.",
    },
    "cimis_live_weather": {
        "label": "CIMIS Live Weather (DWR)",
        "status": "pending_key",
        "description": "California Irrigation Management Information System — official DWR ETo data.",
        "requires_env": ["CIMIS_APP_KEY"],
        "evidence_class": "weather_context",
        "note": "Provides reference ET context. Does not alter groundwater-meter calculations.",
    },
    "public_fcgma_context": {
        "label": "FCGMA Public Context",
        "status": "enabled",
        "description": "Public FCGMA documents: flowmeter requirements, agency forms, interactive map, Resolution 2018-01.",
        "requires_env": [],
        "evidence_class": "public_context",
        "note": "Public reference data only. Not official agency records.",
    },
    "ranch_systems_adapter_pending": {
        "label": "Ranch Systems (Pending Authorization)",
        "status": "disabled",
        "description": "Awaiting official Ranch Systems schema, sample export, or API authorization.",
        "requires_env": ["RANCH_SYSTEMS_API_KEY", "RANCH_SYSTEMS_API_URL"],
        "evidence_class": None,
        "note": (
            "This adapter is intentionally disabled. AGRO-AI does not have a validated "
            "Ranch Systems integration. Do not label any records as Ranch Systems without "
            "official schema and authorization."
        ),
    },
}

# Review status values
REVIEW_STATUSES = {
    "pending_review",
    "under_review",
    "ready_for_export",
    "requires_attention",
    "reviewer_approved",
    "excluded",
}

# Exception types
EXCEPTION_TYPES = {
    "missing_telemetry_interval",
    "meter_reset_detected",
    "multiplier_change",
    "unit_change",
    "duplicate_record",
    "late_arriving_record",
    "pump_activity_without_meter_movement",
    "reverse_flow",
    "unresolved_combcode",
    "unresolved_parcel_mapping",
    "backup_estimate_required",
    "stale_source",
    "negative_delta",
    "missing_mapping",
}

CALCULATION_VERSION = "fcgma-calc-v0.1"

# ─────────────────────────────────────────────
# In-memory store
# ─────────────────────────────────────────────
_LEDGER: dict[str, dict[str, Any]] = {}
_AUDIT_LOG: list[dict[str, Any]] = []
_EXCEPTIONS: dict[str, dict[str, Any]] = {}
_WEATHER_RECORDS: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_hash(provider: str, external_id: str) -> str:
    return hashlib.sha256(f"{provider}:{external_id}".encode()).hexdigest()[:16]


def make_record(
    evidence_class: str,
    provider: str,
    external_source_id: str,
    event_timestamp: str,
    reporting_period: str,
    well_id: str,
    meter_id: str,
    *,
    meter_serial: str | None = None,
    combcode: str | None = None,
    parcel_ids: list[str] | None = None,
    operator_id: str = "operator-anon-001",
    cumulative_volume: float | None = None,
    interval_volume: float | None = None,
    unit: str = "acre-feet",
    unit_original: str | None = None,
    multiplier: float = 1.0,
    pump_status: str | None = None,
    pressure: float | None = None,
    weather_context_id: str | None = None,
    source_quality: str = "ok",
    scenario_injected: bool = False,
    scenario_label: str | None = None,
    exceptions: list[dict[str, Any]] | None = None,
    review_status: str = "pending_review",
    reviewer_notes: str | None = None,
    source_lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if evidence_class not in EVIDENCE_CLASSES:
        raise ValueError(f"Invalid evidence_class: {evidence_class}")
    record_id = f"rec-{uuid.uuid4().hex[:12]}"
    now = _now()
    return {
        "id": record_id,
        "evidence_class": evidence_class,
        "provider": provider,
        "external_source_id": external_source_id,
        "sanitized_source_hash": _source_hash(provider, external_source_id),
        "event_timestamp": event_timestamp,
        "received_timestamp": now,
        "reporting_period": reporting_period,
        "well_id": well_id,
        "meter_id": meter_id,
        "meter_serial": meter_serial,
        "combcode": combcode,
        "parcel_ids": parcel_ids or [],
        "operator_id": operator_id,
        "cumulative_volume": cumulative_volume,
        "interval_volume": interval_volume,
        "unit": unit,
        "unit_original": unit_original or unit,
        "multiplier": multiplier,
        "pump_status": pump_status,
        "pressure": pressure,
        "weather_context_id": weather_context_id,
        "source_lineage": source_lineage or {
            "provider": provider,
            "external_source_id": external_source_id,
            "retrieval_method": "demo_scenario" if scenario_injected else "adapter",
        },
        "source_quality": source_quality,
        "scenario_injected": scenario_injected,
        "scenario_label": scenario_label,
        "calculation_version": CALCULATION_VERSION,
        "exceptions": exceptions or [],
        "review_status": review_status,
        "reviewer_notes": reviewer_notes,
        "audit_events": [
            {
                "event_type": "record_created",
                "timestamp": now,
                "actor": "system",
                "detail": f"Record created from {provider}",
            }
        ],
        "created_at": now,
        "updated_at": now,
    }


# ─────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────

def upsert_record(record: dict[str, Any]) -> dict[str, Any]:
    _LEDGER[record["id"]] = deepcopy(record)
    return deepcopy(record)


def get_record(record_id: str) -> dict[str, Any] | None:
    r = _LEDGER.get(record_id)
    return deepcopy(r) if r else None


def list_records(
    *,
    evidence_class: str | None = None,
    provider: str | None = None,
    review_status: str | None = None,
    scenario_injected: bool | None = None,
    reporting_period: str | None = None,
    has_exceptions: bool | None = None,
) -> list[dict[str, Any]]:
    results = []
    for r in _LEDGER.values():
        if evidence_class and r["evidence_class"] != evidence_class:
            continue
        if provider and r["provider"] != provider:
            continue
        if review_status and r["review_status"] != review_status:
            continue
        if scenario_injected is not None and r["scenario_injected"] != scenario_injected:
            continue
        if reporting_period and r["reporting_period"] != reporting_period:
            continue
        if has_exceptions is not None:
            has = len(r["exceptions"]) > 0
            if has != has_exceptions:
                continue
        results.append(deepcopy(r))
    return sorted(results, key=lambda x: x["event_timestamp"], reverse=True)


def update_review_status(record_id: str, status: str, actor: str = "reviewer", notes: str | None = None) -> dict[str, Any] | None:
    r = _LEDGER.get(record_id)
    if not r:
        return None
    r["review_status"] = status
    r["updated_at"] = _now()
    if notes:
        r["reviewer_notes"] = notes
    r["audit_events"].append({
        "event_type": "review_status_updated",
        "timestamp": _now(),
        "actor": actor,
        "detail": f"Status set to {status}" + (f": {notes}" if notes else ""),
    })
    _LEDGER[record_id] = r
    return deepcopy(r)


def add_audit_event(record_id: str, event_type: str, actor: str, detail: str) -> bool:
    r = _LEDGER.get(record_id)
    if not r:
        return False
    r["audit_events"].append({
        "event_type": event_type,
        "timestamp": _now(),
        "actor": actor,
        "detail": detail,
    })
    r["updated_at"] = _now()
    _LEDGER[record_id] = r
    _AUDIT_LOG.append({"record_id": record_id, "event_type": event_type, "timestamp": _now(), "actor": actor, "detail": detail})
    return True


def resolve_exception(exception_id: str, resolution: str, actor: str) -> dict[str, Any] | None:
    exc = _EXCEPTIONS.get(exception_id)
    if not exc:
        return None
    exc["status"] = "resolved"
    exc["resolution"] = resolution
    exc["resolved_at"] = _now()
    exc["resolved_by"] = actor
    _EXCEPTIONS[exception_id] = exc
    # Update record exception
    record_id = exc.get("record_id")
    r = _LEDGER.get(record_id)
    if r:
        for e in r["exceptions"]:
            if e.get("id") == exception_id:
                e["status"] = "resolved"
                e["resolution"] = resolution
        r["updated_at"] = _now()
        _LEDGER[record_id] = r
    return deepcopy(exc)


def store_exception(exception: dict[str, Any]) -> dict[str, Any]:
    _EXCEPTIONS[exception["id"]] = deepcopy(exception)
    return deepcopy(exception)


def get_exception(exception_id: str) -> dict[str, Any] | None:
    e = _EXCEPTIONS.get(exception_id)
    return deepcopy(e) if e else None


def list_exceptions() -> list[dict[str, Any]]:
    return [deepcopy(e) for e in _EXCEPTIONS.values()]


def clear_ledger() -> None:
    _LEDGER.clear()
    _AUDIT_LOG.clear()
    _EXCEPTIONS.clear()
    _WEATHER_RECORDS.clear()


def ledger_stats() -> dict[str, Any]:
    records = list(_LEDGER.values())
    total = len(records)
    injected = sum(1 for r in records if r["scenario_injected"])
    live = total - injected
    requires_attention = sum(1 for r in records if r["review_status"] == "requires_attention")
    ready = sum(1 for r in records if r["review_status"] == "ready_for_export")
    exceptions_total = sum(len(r["exceptions"]) for r in records)
    open_exceptions = sum(
        1 for e in _EXCEPTIONS.values() if e.get("status") != "resolved"
    )
    classes: dict[str, int] = {}
    for r in records:
        ec = r["evidence_class"]
        classes[ec] = classes.get(ec, 0) + 1

    # Aggregate supported extraction (groundwater_meter_reading only, non-injected where possible)
    af_total: float = 0.0
    af_provisional: float = 0.0
    for r in records:
        iv = r.get("interval_volume")
        if iv is not None and iv > 0 and r["unit"] == "acre-feet":
            if r["evidence_class"] == "groundwater_meter_reading":
                if r["review_status"] in ("ready_for_export", "reviewer_approved"):
                    af_total += iv
                elif r["review_status"] in ("pending_review", "requires_attention", "under_review"):
                    af_provisional += iv

    return {
        "total_records": total,
        "live_records": live,
        "injected_scenario_records": injected,
        "requires_attention": requires_attention,
        "ready_for_export": ready,
        "total_exceptions": exceptions_total,
        "open_exceptions": open_exceptions,
        "evidence_class_breakdown": classes,
        "supported_extraction_af": round(af_total, 4),
        "provisional_af": round(af_provisional, 4),
    }


def upsert_weather_record(record: dict[str, Any]) -> dict[str, Any]:
    _WEATHER_RECORDS[record["id"]] = deepcopy(record)
    return deepcopy(record)


def get_weather_records() -> list[dict[str, Any]]:
    return [deepcopy(r) for r in _WEATHER_RECORDS.values()]
