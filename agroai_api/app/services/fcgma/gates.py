"""Reporting-cycle gate status computation for the FCGMA Water Intelligence Copilot.

Five gates must clear before a reporting package can be submitted to FCGMA:
  Gate 1 — Source Coverage
  Gate 2 — Accounting Integrity
  Gate 3 — Governance & Mapping
  Gate 4 — Reporting Package
  Gate 5 — Submission Readiness (aggregate)

Each gate returns a structured dict with status, status_label, what_remains,
and next_action fields.  compute_all_gates() assembles all five into a single
summary envelope.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .ledger import ledger_stats, list_exceptions, list_records, PROVIDER_REGISTRY, CALCULATION_VERSION
from .cases import build_cases
from .copilot import compare_provider_health, list_unvalidated_assumptions


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _n(count: int, singular: str, plural: str | None = None) -> str:
    """Return pluralised label, e.g. '1 record', '2 records', '1 case', '4 cases'.

    Never uses the '(s)' form.
    """
    word = singular if count == 1 else (plural if plural is not None else singular + "s")
    return f"{count} {word}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open_exceptions_of_type(exc_type: str) -> list[dict[str, Any]]:
    return [
        e for e in list_exceptions()
        if e.get("status") != "resolved" and e.get("exception_type") == exc_type
    ]


def _open_exceptions_of_types(exc_types: set[str]) -> list[dict[str, Any]]:
    return [
        e for e in list_exceptions()
        if e.get("status") != "resolved" and e.get("exception_type") in exc_types
    ]


# ─────────────────────────────────────────────
# Gate 1 — Source Coverage
# ─────────────────────────────────────────────

def compute_gate_1_source_coverage() -> dict[str, Any]:
    """Gate 1: Are all expected data sources connected and delivering complete records?"""
    # expected = providers that are enabled or disabled (not "pending_key")
    expected_sources = sum(
        1 for p in PROVIDER_REGISTRY.values()
        if p["status"] != "pending_key"
    )

    health_result = compare_provider_health()
    providers = health_result.get("providers", [])
    connected_sources = sum(1 for p in providers if p["status"] == "connected")

    stale_feed_count = sum(
        1 for p in PROVIDER_REGISTRY.values()
        if p["status"] in ("pending_key", "unavailable")
    )

    stats = ledger_stats()
    records_received = stats["total_records"]

    missing_interval_exceptions = _open_exceptions_of_type("missing_telemetry_interval")
    missing_interval_count = len(missing_interval_exceptions)

    # Determine status
    if connected_sources == expected_sources and missing_interval_count == 0:
        status = "complete"
        status_label = "Complete"
        what_remains = "All expected sources are connected and delivering complete records."
        next_action = "Proceed to Gate 2 — Accounting Integrity."
    elif connected_sources < expected_sources // 2:
        status = "incomplete"
        status_label = "Incomplete"
        gaps = []
        if connected_sources < expected_sources:
            gaps.append(_n(expected_sources - connected_sources, "source") + " not yet connected")
        if missing_interval_count > 0:
            gaps.append(_n(missing_interval_count, "telemetry gap") + " during confirmed pump activity")
        what_remains = "; ".join(gaps) + "." if gaps else "Source connectivity is critically low."
        next_action = "Configure missing API keys and verify data feeds before proceeding."
    else:
        status = "attention_required"
        status_label = "Attention required"
        gaps = []
        if connected_sources < expected_sources:
            gaps.append(_n(expected_sources - connected_sources, "expected source") + " not connected")
        if stale_feed_count > 0:
            gaps.append(_n(stale_feed_count, "feed") + " pending configuration")
        if missing_interval_count > 0:
            gaps.append(_n(missing_interval_count, "telemetry interval gap") + " open")
        what_remains = "; ".join(gaps) + "." if gaps else "Minor source issues require attention."
        next_action = (
            "Resolve missing telemetry intervals and configure stale feeds."
            if missing_interval_count > 0
            else "Configure pending API keys to complete source coverage."
        )

    return {
        "gate": 1,
        "name": "Source Coverage",
        "expected_sources": expected_sources,
        "connected_sources": connected_sources,
        "records_received": records_received,
        "stale_feed_count": stale_feed_count,
        "missing_interval_count": missing_interval_count,
        "providers": providers,
        "status": status,
        "status_label": status_label,
        "what_remains": what_remains,
        "next_action": next_action,
        "calculation_version": CALCULATION_VERSION,
    }


# ─────────────────────────────────────────────
# Gate 2 — Accounting Integrity
# ─────────────────────────────────────────────

_ACCOUNTING_CASE_TYPES = {
    "meter_reset",
    "missing_interval",
    "backup_estimate",
    "multiplier_change",
    # Normalised to exception_type names as used in issue_categories
    "meter_reset_detected",
    "missing_telemetry_interval",
    "backup_estimate_required",
}


def compute_gate_2_accounting() -> dict[str, Any]:
    """Gate 2: Are all extraction quantities supported and free of material discrepancies?"""
    stats = ledger_stats()
    records_assessed = stats["total_records"]
    records_cleared = stats["ready_for_export"]
    records_under_review = stats["requires_attention"]
    supported_quantity_af = stats["supported_extraction_af"]
    quantity_under_review_af = stats["provisional_af"]

    excluded_interval_count = len(_open_exceptions_of_type("meter_reset_detected"))

    all_cases = build_cases()
    accounting_types = {
        "meter_reset_detected", "missing_telemetry_interval",
        "backup_estimate_required", "multiplier_change",
    }
    material_cases = [
        c for c in all_cases
        if any(cat in accounting_types for cat in c.get("issue_categories", []))
    ]
    material_case_count = len(material_cases)

    high_severity_material = [c for c in material_cases if c.get("severity") == "high"]

    if material_case_count == 0:
        status = "cleared"
        status_label = "Cleared"
        what_remains = "No material accounting cases remain. All quantities are supported."
        next_action = "Proceed to Gate 3 — Governance."
    elif len(high_severity_material) >= 3:
        status = "blocked"
        status_label = "Blocked"
        affected_af = sum(c.get("affected_quantity_af", 0) for c in high_severity_material)
        what_remains = (
            f"{_n(len(high_severity_material), 'high-severity case')} block accounting close, "
            f"affecting {affected_af:.2f} AF."
        )
        next_action = "Resolve high-severity meter reset and backup estimate cases before proceeding."
    else:
        status = "action_required"
        status_label = "Action required"
        affected_af = sum(c.get("affected_quantity_af", 0) for c in material_cases)
        what_remains = (
            f"{_n(material_case_count, 'material case')} open, "
            f"affecting {affected_af:.2f} AF under review."
        )
        next_action = (
            f"Resolve {_n(material_case_count, 'accounting case')} "
            "(meter reset, telemetry gap, or multiplier change) to clear this gate."
        )

    return {
        "gate": 2,
        "name": "Accounting Integrity",
        "records_assessed": records_assessed,
        "records_cleared": records_cleared,
        "records_under_review": records_under_review,
        "supported_quantity_af": supported_quantity_af,
        "quantity_under_review_af": quantity_under_review_af,
        "excluded_interval_count": excluded_interval_count,
        "material_cases": material_cases,
        "material_case_count": material_case_count,
        "status": status,
        "status_label": status_label,
        "what_remains": what_remains,
        "next_action": next_action,
        "calculation_version": CALCULATION_VERSION,
    }


# ─────────────────────────────────────────────
# Gate 3 — Governance & Mapping
# ─────────────────────────────────────────────

def compute_gate_3_governance() -> dict[str, Any]:
    """Gate 3: Are CombCode mappings, parcel assignments, and operator confirmations complete?"""
    combcode_pending_count = len(_open_exceptions_of_type("unresolved_combcode"))
    parcel_mapping_pending_count = len(_open_exceptions_of_type("unresolved_parcel_mapping"))

    operator_exception_types = {
        "pump_activity_without_meter_movement",
        "backup_estimate_required",
    }
    operator_confirmations_pending = len(_open_exceptions_of_types(operator_exception_types))

    reviewer_actions_pending = len(list_records(review_status="requires_attention"))

    assumptions_result = list_unvalidated_assumptions()
    unvalidated_assumptions = assumptions_result.get("assumption_count", 0)

    all_zero = (
        combcode_pending_count == 0
        and parcel_mapping_pending_count == 0
        and operator_confirmations_pending == 0
        and reviewer_actions_pending == 0
    )

    if all_zero:
        status = "cleared"
        status_label = "Cleared"
        what_remains = "All governance items are resolved. CombCodes, parcel mappings, and operator confirmations are complete."
        next_action = "Proceed to Gate 4 — Reporting Package."
    elif combcode_pending_count > 0 or parcel_mapping_pending_count > 0:
        status = "blocked"
        status_label = "Blocked"
        parts = []
        if combcode_pending_count > 0:
            parts.append(_n(combcode_pending_count, "CombCode") + " unresolved")
        if parcel_mapping_pending_count > 0:
            parts.append(_n(parcel_mapping_pending_count, "parcel mapping") + " unresolved")
        if operator_confirmations_pending > 0:
            parts.append(_n(operator_confirmations_pending, "operator confirmation") + " pending")
        what_remains = "; ".join(parts) + "."
        next_action = (
            "Obtain confirmed CombCodes from FCGMA for all unresolved wells before this gate can clear."
        )
    else:
        status = "awaiting_confirmation"
        status_label = "Awaiting confirmation"
        parts = []
        if operator_confirmations_pending > 0:
            parts.append(_n(operator_confirmations_pending, "operator confirmation") + " outstanding")
        if reviewer_actions_pending > 0:
            parts.append(_n(reviewer_actions_pending, "record") + " pending reviewer action")
        what_remains = "; ".join(parts) + "." if parts else "Minor confirmations pending."
        next_action = (
            "Contact field operators to confirm pump activity and backup estimate requirements."
            if operator_confirmations_pending > 0
            else "Complete reviewer actions on flagged records."
        )

    return {
        "gate": 3,
        "name": "Governance & Mapping",
        "combcode_pending_count": combcode_pending_count,
        "parcel_mapping_pending_count": parcel_mapping_pending_count,
        "operator_confirmations_pending": operator_confirmations_pending,
        "reviewer_actions_pending": reviewer_actions_pending,
        "unvalidated_assumptions": unvalidated_assumptions,
        "status": status,
        "status_label": status_label,
        "what_remains": what_remains,
        "next_action": next_action,
        "calculation_version": CALCULATION_VERSION,
    }


# ─────────────────────────────────────────────
# Gate 4 — Reporting Package
# ─────────────────────────────────────────────

def compute_gate_4_reporting_package() -> dict[str, Any]:
    """Gate 4: Has a reporting package (executive brief + exception packet) been generated?"""
    from .reports import _REPORTS

    stats = ledger_stats()
    evidence_bundle_count = (
        len(list_records(review_status="ready_for_export"))
        + len(list_records(review_status="reviewer_approved"))
    )

    # Find the most recently generated reports of each type
    # Reports don't have a formal 'type' field in the current schema — we use
    # the presence of artifacts to identify them.  All generated reports from
    # generate_report() serve as the executive brief / exception packet proxy.
    all_reports = sorted(
        _REPORTS.values(),
        key=lambda r: r.get("generated_at", ""),
        reverse=True,
    )

    latest_brief = None
    exception_packet = None

    for r in all_reports:
        artifacts = [a.get("name", "") for a in r.get("artifacts", [])]
        if "executive_pdf" in artifacts and latest_brief is None:
            latest_brief = {
                "report_id": r.get("report_id"),
                "generated_at": r.get("generated_at"),
                "record_count": r.get("record_count"),
                "exception_count": r.get("exception_count"),
            }
        if "exceptions_csv" in artifacts and exception_packet is None:
            exception_packet = {
                "report_id": r.get("report_id"),
                "generated_at": r.get("generated_at"),
                "exception_count": r.get("exception_count"),
            }
        if latest_brief and exception_packet:
            break

    # Determine freshness: if the report record count matches current record count,
    # treat it as current.  Otherwise it may be stale.
    current_record_count = stats["total_records"]

    if latest_brief is None:
        status = "not_generated"
        status_label = "Not generated"
        what_remains = "No executive brief has been generated for this reporting cycle."
        next_action = "Generate the reporting package (executive brief and exception packet) now."
    elif latest_brief.get("record_count") == current_record_count:
        status = "ready"
        status_label = "Ready"
        what_remains = "Reporting package is current and reflects the latest ledger state."
        next_action = "Review the package with the Executive Officer before submission."
    else:
        status = "draft_available"
        status_label = "Draft available"
        delta = current_record_count - (latest_brief.get("record_count") or 0)
        what_remains = (
            f"An existing brief was generated when {latest_brief.get('record_count', 0)} "
            f"{('record was' if (latest_brief.get('record_count') or 0) == 1 else 'records were')} in the ledger; "
            f"the ledger has since changed by {abs(delta)} "
            f"{'record' if abs(delta) == 1 else 'records'}."
        )
        next_action = "Regenerate the reporting package to reflect the current ledger state."

    return {
        "gate": 4,
        "name": "Reporting Package",
        "latest_brief": latest_brief,
        "exception_packet": exception_packet,
        "evidence_bundle_count": evidence_bundle_count,
        "status": status,
        "status_label": status_label,
        "what_remains": what_remains,
        "next_action": next_action,
        "calculation_version": CALCULATION_VERSION,
    }


# ─────────────────────────────────────────────
# Gate 5 — Submission Readiness
# ─────────────────────────────────────────────

def compute_gate_5_submission_readiness() -> dict[str, Any]:
    """Gate 5: Is the reporting cycle ready to close and submit to FCGMA?"""
    gate1 = compute_gate_1_source_coverage()
    gate2 = compute_gate_2_accounting()
    gate3 = compute_gate_3_governance()
    gate4 = compute_gate_4_reporting_package()

    all_cases = build_cases()
    blocking_cases = [
        c for c in all_cases
        if c.get("status") == "open" and c.get("severity") == "high"
    ]
    blocking_case_count = len(blocking_cases)
    quantity_affected_af = round(
        sum(c.get("affected_quantity_af", 0) for c in blocking_cases), 4
    )
    evidence_requests_outstanding = sum(
        len(c.get("required_evidence", [])) for c in all_cases if c.get("status") == "open"
    )
    required_reviewer_actions = gate3["reviewer_actions_pending"]

    # Blocking gates
    gate_statuses = {
        1: gate1["status"],
        2: gate2["status"],
        3: gate3["status"],
        4: gate4["status"],
    }
    blocked_gates = [g for g, s in gate_statuses.items() if s in ("blocked", "incomplete")]
    pending_gates = [g for g, s in gate_statuses.items() if s in ("action_required", "attention_required", "awaiting_confirmation", "draft_available")]

    if not blocked_gates and not pending_gates and blocking_case_count == 0:
        status = "ready_to_close"
        status_label = "Ready to close"
        plain_english = (
            "All five reporting gates are clear. The ledger is clean, all quantities are "
            "supported, governance items are resolved, and the reporting package is current. "
            "This cycle is ready to submit to FCGMA."
        )
        what_remains = "No blocking items. Confirm final review with the Executive Officer."
        next_action = "Initiate formal submission review with the Executive Officer."
    elif not blocked_gates and blocking_case_count == 0:
        status = "awaiting_approval"
        status_label = "Awaiting approval"
        pending_desc = _n(len(pending_gates), "gate") + " pending minor items"
        plain_english = (
            f"The cycle is nearly ready. {pending_desc.capitalize()} — no high-severity cases remain. "
            "Remaining items are confirmations and package freshness checks that can be resolved quickly."
        )
        what_remains = pending_desc + "."
        next_action = "Complete outstanding confirmations and regenerate the reporting package if stale."
    else:
        status = "not_ready"
        status_label = "Not ready"
        parts = []
        if blocking_case_count > 0:
            parts.append(
                f"{_n(blocking_case_count, 'high-severity case')} open, "
                f"affecting {quantity_affected_af:.2f} AF"
            )
        if blocked_gates:
            parts.append(f"{_n(len(blocked_gates), 'gate')} blocked")
        plain_english = (
            f"The cycle is not ready to submit. "
            + "; ".join(parts)
            + ". Resolve blocking cases and recheck all gates before initiating submission."
        )
        what_remains = "; ".join(parts) + "."
        next_action = (
            "Resolve all high-severity cases and clear blocked gates before submission."
        )

    return {
        "gate": 5,
        "name": "Submission Readiness",
        "blocking_case_count": blocking_case_count,
        "quantity_affected_af": quantity_affected_af,
        "evidence_requests_outstanding": evidence_requests_outstanding,
        "required_reviewer_actions": required_reviewer_actions,
        "gate_statuses": gate_statuses,
        "plain_english": plain_english,
        "status": status,
        "status_label": status_label,
        "what_remains": what_remains,
        "next_action": next_action,
        "calculation_version": CALCULATION_VERSION,
    }


# ─────────────────────────────────────────────
# Aggregate
# ─────────────────────────────────────────────

def compute_all_gates() -> dict[str, Any]:
    """Compute all five gates and return a summary envelope."""
    gate1 = compute_gate_1_source_coverage()
    gate2 = compute_gate_2_accounting()
    gate3 = compute_gate_3_governance()
    gate4 = compute_gate_4_reporting_package()
    gate5 = compute_gate_5_submission_readiness()

    gates = [gate1, gate2, gate3, gate4, gate5]

    # Count clear / attention / blocked
    clear_count = sum(
        1 for g in gates[:4]
        if g["status"] in ("complete", "cleared", "ready")
    )
    attention_count = sum(
        1 for g in gates[:4]
        if g["status"] in ("attention_required", "action_required", "awaiting_confirmation", "draft_available")
    )
    blocked_count = sum(
        1 for g in gates[:4]
        if g["status"] in ("blocked", "incomplete", "not_generated")
    )

    material_case_count = gate2.get("material_case_count", 0)
    quantity_under_review = gate2.get("quantity_under_review_af", 0.0)

    # Build natural summary
    if clear_count == 4:
        summary_position = (
            "All four prerequisite gates are clear. The cycle is ready for submission review."
        )
    elif blocked_count > 0:
        summary_position = (
            f"{_n(clear_count, 'gate')} of four are clear. "
            f"{_n(blocked_count, 'gate')} {'is' if blocked_count == 1 else 'are'} blocked."
            + (
                f" {_n(material_case_count, 'material case')} remain open, "
                f"affecting {quantity_under_review:.2f} AF currently under review."
                if material_case_count > 0 else ""
            )
        )
    else:
        summary_position = (
            f"{_n(clear_count, 'gate')} of four are clear. "
            f"{_n(attention_count, 'gate')} {'requires' if attention_count == 1 else 'require'} attention."
            + (
                f" {_n(material_case_count, 'material case')} remain open, "
                f"affecting {quantity_under_review:.2f} AF currently under review."
                if material_case_count > 0 else ""
            )
        )

    return {
        "reporting_period": "2026-Q1",
        "submission_deadline": "2026-04-30",
        "gates": gates,
        "summary_position": summary_position,
        "gate_summary": {
            "clear": clear_count,
            "attention": attention_count,
            "blocked": blocked_count,
        },
        "generated_at": _now(),
        "calculation_version": CALCULATION_VERSION,
    }
