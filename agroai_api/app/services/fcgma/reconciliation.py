"""ReconciliationSnapshot — versioned water-accounting state for the FCGMA Copilot.

Each snapshot captures the complete ledger position at a point in time:
all nine defined water-accounting quantities, gate statuses, case counts,
and the source-lineage evidence that supports each quantity.

Water-accounting quantities defined (DEMO RULESET v0.1):
  1. total_extraction_af         — raw sum of all interval volumes
  2. supported_extraction_af     — quantities with cleared exceptions
  3. provisional_af              — quantities pending exception resolution
  4. quarantined_af              — volumes excluded (meter-reset intervals)
  5. confirmed_applied_water_af  — supported + confirmed attribution
  6. provisional_applied_water_af — attributed but CombCode / parcel pending
  7. unattributed_af             — no attribution possible yet
  8. quantity_under_review_af    — active exception review in progress
  9. total_reported_af           — total to be included in FCGMA submission

All quantities are provisional until Fox Canyon validates the applied-water model.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .ledger import (
    _LEDGER,
    _EXCEPTIONS,
    CALCULATION_VERSION,
    ledger_stats,
    list_exceptions,
    list_records,
)
from .gates import compute_all_gates
from .cases import build_cases
from .calculation_engine import run_full_calculation_pass


# ─────────────────────────────────────────────
# In-memory store
# ─────────────────────────────────────────────

_SNAPSHOTS: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snap_id() -> str:
    return f"snap-{uuid.uuid4().hex[:12]}"


# ─────────────────────────────────────────────
# Snapshot creation
# ─────────────────────────────────────────────

def _compute_quantities(stats: dict[str, Any]) -> dict[str, float]:
    """Derive the nine defined water-accounting quantities from ledger stats."""
    records = list_records()
    exceptions = list_exceptions()
    open_excs = [e for e in exceptions if e.get("status") != "resolved"]

    total_extraction_af = sum(
        (r.get("interval_volume") or 0) for r in records if not r.get("interval_quarantined")
    )
    quarantined_af = sum(
        abs(r.get("interval_quarantine_delta") or 0)
        for r in records if r.get("interval_quarantined")
    )
    supported_extraction_af = stats.get("supported_extraction_af", 0.0)
    provisional_af = stats.get("provisional_af", 0.0)

    confirmed_applied_water_af = sum(
        (r.get("confirmed_applied_water_af") or 0) for r in records
    )
    provisional_applied_water_af = sum(
        (r.get("provisional_applied_water_af") or 0) for r in records
    )

    attributed_total = confirmed_applied_water_af + provisional_applied_water_af
    unattributed_af = max(0.0, total_extraction_af - attributed_total)

    quantity_under_review_af = provisional_af

    # total_reported_af = supported quantities that are cleared for export
    ready_records = list_records(review_status="ready_for_export") + list_records(review_status="reviewer_approved")
    total_reported_af = sum((r.get("interval_volume") or 0) for r in ready_records)

    return {
        "total_extraction_af": round(total_extraction_af, 4),
        "supported_extraction_af": round(supported_extraction_af, 4),
        "provisional_af": round(provisional_af, 4),
        "quarantined_af": round(quarantined_af, 4),
        "confirmed_applied_water_af": round(confirmed_applied_water_af, 4),
        "provisional_applied_water_af": round(provisional_applied_water_af, 4),
        "unattributed_af": round(unattributed_af, 4),
        "quantity_under_review_af": round(quantity_under_review_af, 4),
        "total_reported_af": round(total_reported_af, 4),
    }


def _compute_source_coverage() -> dict[str, Any]:
    """Derive source coverage from the ledger."""
    from .ledger import PROVIDER_REGISTRY
    import os
    sources = []
    for pid, preg in PROVIDER_REGISTRY.items():
        missing = [e for e in preg["requires_env"] if not os.getenv(e, "").strip()]
        if preg["status"] == "disabled":
            status = "disabled"
        elif missing:
            status = "unavailable"
        else:
            status = "connected"
        sources.append({
            "provider_id": pid,
            "label": preg["label"],
            "status": status,
        })
    connected = sum(1 for s in sources if s["status"] == "connected")
    return {
        "sources": sources,
        "total_sources": len(sources),
        "connected_sources": connected,
        "coverage_pct": round(connected / len(sources) * 100, 1) if sources else 0.0,
    }


def create_snapshot(
    triggered_by: str = "manual",
    on_progress: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """Run full calculation pass and capture a ReconciliationSnapshot."""

    def _emit(stage: str, label: str) -> None:
        if on_progress:
            on_progress(stage, label)

    _emit("start", "Starting reconciliation pass…")

    # Run calculation engine
    _emit("calculation_pass", "Running calculation pass over all records…")
    calc_result = run_full_calculation_pass()
    _emit("calculation_pass_done", f"Processed {calc_result['records_processed']} records")

    # Gather post-pass data
    _emit("gather_quantities", "Computing water-accounting quantities…")
    stats = ledger_stats()
    quantities = _compute_quantities(stats)

    _emit("gather_gates", "Evaluating five reporting gates…")
    gates = compute_all_gates()

    _emit("gather_cases", "Grouping exception cases…")
    cases = build_cases()
    open_cases = [c for c in cases if c.get("status") == "open"]
    high_cases = [c for c in open_cases if c.get("severity") == "high"]

    _emit("gather_sources", "Checking source coverage…")
    source_coverage = _compute_source_coverage()

    # Build lineage evidence chain
    exceptions = list_exceptions()
    open_excs = [e for e in exceptions if e.get("status") != "resolved"]
    exc_by_type: dict[str, int] = {}
    for e in open_excs:
        t = e.get("exception_type", "unknown")
        exc_by_type[t] = exc_by_type.get(t, 0) + 1

    sid = _snap_id()
    now = _now()

    snap: dict[str, Any] = {
        "id": sid,
        "created_at": now,
        "triggered_by": triggered_by,
        "calculation_version": CALCULATION_VERSION,
        "applied_water_model": "DEMO RULESET v0.1",
        "applied_water_model_status": "provisional",

        # Record counts
        "total_records": stats.get("total_records", 0),
        "records_cleared": stats.get("ready_for_export", 0),
        "records_under_review": stats.get("requires_attention", 0),
        "records_pending": stats.get("pending_review", 0),

        # Nine water-accounting quantities
        **quantities,

        # Gate status snapshot
        "gates_clear": gates["gate_summary"]["clear"],
        "gates_attention": gates["gate_summary"]["attention"],
        "gates_blocked": gates["gate_summary"]["blocked"],
        "gates_total": gates["gate_summary"]["total"],
        "gate_5_status": gates["gates"][-1]["status"] if gates.get("gates") else "unknown",
        "gate_5_label": gates["gates"][-1]["status_label"] if gates.get("gates") else "Unknown",
        "summary_position": gates.get("summary_position", ""),

        # Case counts
        "total_cases": len(cases),
        "open_cases": len(open_cases),
        "high_severity_cases": len(high_cases),

        # Exception summary
        "total_exceptions": len(exceptions),
        "open_exceptions": len(open_excs),
        "exception_type_summary": exc_by_type,

        # Source coverage
        "source_coverage": source_coverage,

        # Calculation pass result
        "records_processed": calc_result["records_processed"],
        "exceptions_raised_this_pass": calc_result["exceptions_raised"],

        "disclaimer": (
            "All quantities are from demonstration scenarios. "
            "Not an official Fox Canyon reporting snapshot."
        ),
    }

    _SNAPSHOTS[sid] = snap
    _emit("done", f"Snapshot {sid} created")
    return snap


# ─────────────────────────────────────────────
# Retrieval
# ─────────────────────────────────────────────

def get_latest_snapshot() -> dict[str, Any] | None:
    if not _SNAPSHOTS:
        return None
    return max(_SNAPSHOTS.values(), key=lambda s: s["created_at"])


def get_snapshot(snap_id: str) -> dict[str, Any] | None:
    return _SNAPSHOTS.get(snap_id)


def list_snapshots() -> list[dict[str, Any]]:
    return sorted(_SNAPSHOTS.values(), key=lambda s: s["created_at"], reverse=True)


# ─────────────────────────────────────────────
# Comparison
# ─────────────────────────────────────────────

_QUANTITY_KEYS = [
    "total_extraction_af", "supported_extraction_af", "provisional_af",
    "quarantined_af", "confirmed_applied_water_af", "provisional_applied_water_af",
    "unattributed_af", "quantity_under_review_af", "total_reported_af",
]

_COUNT_KEYS = [
    "total_records", "records_cleared", "records_under_review",
    "total_cases", "open_cases", "high_severity_cases",
    "total_exceptions", "open_exceptions",
    "gates_clear", "gates_attention", "gates_blocked",
]


def compare_snapshots(snap_id: str, prior_id: str) -> dict[str, Any] | None:
    """Return a structured diff between two snapshots (current vs prior)."""
    current = _SNAPSHOTS.get(snap_id)
    prior = _SNAPSHOTS.get(prior_id)
    if not current or not prior:
        return None

    quantity_changes: list[dict[str, Any]] = []
    for key in _QUANTITY_KEYS:
        cur_val = current.get(key, 0.0)
        pri_val = prior.get(key, 0.0)
        delta = round(cur_val - pri_val, 4)
        if delta != 0:
            quantity_changes.append({
                "quantity": key,
                "prior": pri_val,
                "current": cur_val,
                "delta": delta,
                "direction": "increase" if delta > 0 else "decrease",
            })

    count_changes: list[dict[str, Any]] = []
    for key in _COUNT_KEYS:
        cur_val = current.get(key, 0)
        pri_val = prior.get(key, 0)
        delta = cur_val - pri_val
        if delta != 0:
            count_changes.append({
                "field": key,
                "prior": pri_val,
                "current": cur_val,
                "delta": delta,
            })

    gate_change = current.get("gate_5_status") != prior.get("gate_5_status")

    return {
        "snapshot_id": snap_id,
        "prior_id": prior_id,
        "snapshot_created_at": current["created_at"],
        "prior_created_at": prior["created_at"],
        "quantity_changes": quantity_changes,
        "count_changes": count_changes,
        "gate_5_changed": gate_change,
        "gate_5_prior": prior.get("gate_5_label"),
        "gate_5_current": current.get("gate_5_label"),
        "has_changes": bool(quantity_changes or count_changes or gate_change),
        "calculation_version": CALCULATION_VERSION,
    }
