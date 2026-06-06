"""Source-to-report lineage tracing for the FCGMA Water Intelligence Copilot.

Lineage answers the question: "Where did this quantity come from, and
what steps transformed it into its current state?"

Lineage for a record traces:
  raw_source → normalization → multiplier_application → interval_calculation
  → exception_detection → attribution → review_status → reporting_readiness

Lineage for a case traces the same path for all contributing records.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .ledger import get_record, CALCULATION_VERSION
from .cases import build_cases
from .calculation_engine import get_calculation_explanation


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────
# Record lineage
# ─────────────────────────────────────────────

def get_record_lineage(record_id: str) -> dict[str, Any] | None:
    """Return the full source-to-report lineage trail for a single record."""
    r = get_record(record_id)
    if not r:
        return None

    explanation = get_calculation_explanation(r)
    audit_events = r.get("audit_events", [])
    open_excs = [e for e in r.get("exceptions", []) if e.get("status") != "resolved"]
    resolved_excs = [e for e in r.get("exceptions", []) if e.get("status") == "resolved"]

    # Build ordered lineage steps
    steps: list[dict[str, Any]] = []

    # Step 1: Raw ingestion
    source_lineage = r.get("source_lineage", {})
    steps.append({
        "step": 1,
        "stage": "raw_ingestion",
        "label": "Raw source ingestion",
        "provider": r.get("provider"),
        "external_source_id": r.get("external_source_id"),
        "retrieval_method": source_lineage.get("retrieval_method", "unknown"),
        "sanitized_source_hash": r.get("sanitized_source_hash"),
        "original_unit": r.get("unit_original"),
        "raw_cumulative_volume": r.get("cumulative_volume"),
        "scenario_injected": r.get("scenario_injected"),
        "scenario_label": r.get("scenario_label"),
        "status": "completed",
        "evidence_class": r.get("evidence_class"),
    })

    # Step 2: Calculation steps (from explanation)
    for i, calc_step in enumerate(explanation.get("steps", []), start=2):
        steps.append({
            "step": i,
            "stage": calc_step["step"],
            "label": calc_step["step"].replace("_", " ").title(),
            "description": calc_step["description"],
            "rule_id": calc_step.get("rule_id"),
            "status": "completed",
        })

    # Step 3: Exception detection
    exc_step = len(steps) + 1
    if open_excs or resolved_excs:
        steps.append({
            "step": exc_step,
            "stage": "exception_detection",
            "label": "Exception detection",
            "open_exceptions": [
                {"id": e["id"], "type": e["exception_type"], "severity": e["severity"]}
                for e in open_excs
            ],
            "resolved_exceptions": [
                {"id": e["id"], "type": e["exception_type"]}
                for e in resolved_excs
            ],
            "status": "open_exceptions" if open_excs else "cleared",
        })

    # Step 4: Attribution
    attr_step = len(steps) + 1
    steps.append({
        "step": attr_step,
        "stage": "attribution",
        "label": "Applied-water attribution",
        "attribution_provisional": r.get("attribution_provisional"),
        "attribution_model": r.get("attribution_model"),
        "confirmed_applied_water_af": r.get("confirmed_applied_water_af"),
        "provisional_applied_water_af": r.get("provisional_applied_water_af"),
        "combcode": r.get("combcode"),
        "parcel_ids": r.get("parcel_ids"),
        "status": "provisional" if r.get("attribution_provisional") else "confirmed",
    })

    # Step 5: Review status
    review_step = len(steps) + 1
    steps.append({
        "step": review_step,
        "stage": "review_status",
        "label": "Review status",
        "review_status": r.get("review_status"),
        "reviewer_notes": r.get("reviewer_notes"),
        "status": r.get("review_status", "unknown"),
    })

    # Step 6: Reporting readiness
    final_step = len(steps) + 1
    reporting_eligible = r.get("review_status") in ("ready_for_export", "reviewer_approved")
    steps.append({
        "step": final_step,
        "stage": "reporting_readiness",
        "label": "Reporting readiness",
        "eligible_for_reporting": reporting_eligible,
        "interval_volume_af": r.get("interval_volume"),
        "status": "eligible" if reporting_eligible else "not_eligible",
    })

    return {
        "record_id": record_id,
        "well_id": r.get("well_id"),
        "meter_id": r.get("meter_id"),
        "provider": r.get("provider"),
        "event_timestamp": r.get("event_timestamp"),
        "reporting_period": r.get("reporting_period"),
        "review_status": r.get("review_status"),
        "lineage_steps": steps,
        "audit_events": audit_events,
        "calculation_version": CALCULATION_VERSION,
        "generated_at": _now(),
        "disclaimer": (
            "Lineage trace is from demonstration scenarios only. "
            "Not an official Fox Canyon audit trail."
        ),
        "model_disclaimer": explanation.get("model_disclaimer", ""),
    }


# ─────────────────────────────────────────────
# Case lineage
# ─────────────────────────────────────────────

def get_case_lineage(case_id: str) -> dict[str, Any] | None:
    """Return the lineage trail for all records contributing to a ReviewCase."""
    all_cases = build_cases()
    case = next((c for c in all_cases if c.get("case_id") == case_id), None)
    if not case:
        return None

    record_lineages = []
    for rid in case.get("record_ids", []):
        rl = get_record_lineage(rid)
        if rl:
            record_lineages.append({
                "record_id": rid,
                "well_id": rl["well_id"],
                "provider": rl["provider"],
                "event_timestamp": rl["event_timestamp"],
                "review_status": rl["review_status"],
                "step_count": len(rl["lineage_steps"]),
                "lineage_steps": rl["lineage_steps"],
            })

    total_af = round(
        sum(
            next(
                (s["interval_volume_af"] or 0 for s in rl["lineage_steps"]
                 if s["stage"] == "reporting_readiness"),
                0,
            )
            for rl in record_lineages
        ),
        4,
    )

    return {
        "case_id": case_id,
        "well_id": case.get("well_id"),
        "reporting_period": case.get("reporting_period"),
        "primary_issue": case.get("primary_issue"),
        "issue_categories": case.get("issue_categories", []),
        "severity": case.get("severity"),
        "affected_quantity_af": case.get("affected_quantity_af"),
        "total_lineage_af": total_af,
        "record_count": len(record_lineages),
        "record_lineages": record_lineages,
        "required_evidence": case.get("required_evidence", []),
        "calculation_version": CALCULATION_VERSION,
        "generated_at": _now(),
        "disclaimer": (
            "Case lineage is from demonstration scenarios only. "
            "Not an official Fox Canyon audit trail."
        ),
    }
