"""Terris — AGRO-AI Water Intelligence Agent.

Terris investigates meter records, source health, mapping integrity,
applied-water calculations, reporting readiness, and unresolved exceptions
to deliver evidence-backed operational answers.

Investigation workflow:
  classify_intent → identify_tools → invoke_tools → inspect_records →
  reconcile_calculations → inspect_lineage → identify_assumptions →
  synthesize_answer → recommend_action → expose_follow_up

All stages reflect real tools invoked — no fabricated progress or fake delays.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from .ledger import (
    get_record,
    ledger_stats,
    list_exceptions,
    list_records,
    PROVIDER_REGISTRY,
    CALCULATION_VERSION,
)
from .calculation_engine import get_calculation_explanation
from .rule_pack import get_rules
from .copilot import (
    get_executive_summary,
    list_records_requiring_attention,
    explain_record,
    get_water_ledger,
    compare_provider_health,
    show_data_lineage,
    list_unvalidated_assumptions,
    run_applied_water_scenario,
    generate_reporting_summary,
    generate_exception_report,
    draft_operator_follow_up,
    _recommend_action,
    _format_deterministic_answer,
    _llm_format,
    TOOL_MAP,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "Terris"
AGENT_DESCRIPTION = (
    "Terris investigates meter records, source health, mapping integrity, "
    "applied-water calculations, reporting readiness, and unresolved exceptions "
    "to deliver evidence-backed operational answers."
)


# ─────────────────────────────────────────────
# New Terris tools
# ─────────────────────────────────────────────

def get_reporting_cycle_status() -> dict[str, Any]:
    """Returns the current reporting cycle status and readiness metrics."""
    stats = ledger_stats()
    exceptions = list_exceptions()
    open_excs = [e for e in exceptions if e.get("status") != "resolved"]

    total = stats["total_records"]
    ready = stats["ready_for_export"]
    requires_attn = stats["requires_attention"]
    readiness_pct = round((ready / total * 100), 1) if total > 0 else 0.0

    exception_type_summary: dict[str, int] = {}
    for e in open_excs:
        t = e["exception_type"]
        exception_type_summary[t] = exception_type_summary.get(t, 0) + 1

    if readiness_pct >= 80 and len(open_excs) == 0:
        cycle_status = "ready_for_review"
        status_label = "Ready for review"
    elif readiness_pct >= 50:
        cycle_status = "in_progress"
        status_label = "In progress — action required"
    else:
        cycle_status = "needs_attention"
        status_label = "Needs attention before cycle can close"

    return {
        "tool": "get_reporting_cycle_status",
        "reporting_period": "2026-Q1",
        "submission_deadline": "2026-04-30",
        "readiness_percentage": readiness_pct,
        "total_records": total,
        "ready_for_export": ready,
        "requires_attention": requires_attn,
        "blocking_exceptions": len(open_excs),
        "exception_type_summary": exception_type_summary,
        "cycle_status": cycle_status,
        "status_label": status_label,
        "supported_extraction_af": stats["supported_extraction_af"],
        "provisional_af": stats["provisional_af"],
        "answer_type": "fact+calculation",
        "calculation_version": CALCULATION_VERSION,
    }


def list_priority_actions() -> dict[str, Any]:
    """Returns a ranked action queue for the current reporting cycle."""
    records = list_records(review_status="requires_attention")

    PRIORITY_ORDER = {
        "pump_activity_without_meter_movement": 1,
        "meter_reset_detected": 2,
        "backup_estimate_required": 3,
        "unresolved_combcode": 4,
        "duplicate_record": 5,
        "missing_telemetry_interval": 6,
        "reverse_flow": 7,
        "multiplier_change": 8,
        "unit_change": 9,
        "unresolved_parcel_mapping": 10,
        "late_arriving_record": 11,
        "negative_delta": 12,
    }

    # Build map of record_id → global open exceptions to catch exceptions that
    # are in the global store but not yet embedded in the record (e.g. pump_activity
    # detected by run_full_calculation_pass after initial record creation)
    global_exc_by_record: dict[str, list[dict]] = {}
    for exc in list_exceptions():
        if exc.get("status") != "resolved":
            rid = exc.get("record_id")
            if rid:
                global_exc_by_record.setdefault(rid, []).append(exc)

    seen_exc_ids: set[str] = set()
    actions = []
    for r in records:
        # Merge embedded + global exceptions, deduplicating by exception id
        embedded = {e["id"]: e for e in r.get("exceptions", []) if e.get("status") != "resolved"}
        global_excs = {e["id"]: e for e in global_exc_by_record.get(r["id"], [])}
        merged = {**global_excs, **embedded}
        for exc_id, e in merged.items():
            if exc_id in seen_exc_ids:
                continue
            seen_exc_ids.add(exc_id)
            priority = PRIORITY_ORDER.get(e["exception_type"], 20)
            actions.append({
                "record_id": r["id"],
                "well_id": r["well_id"],
                "exception_type": e["exception_type"],
                "severity": e.get("severity", "medium"),
                "priority_rank": priority,
                "detail": (e.get("detail") or "")[:120],
                "recommended_action": _recommend_action(e["exception_type"]),
                "scenario_injected": r["scenario_injected"],
            })

    actions.sort(key=lambda x: x["priority_rank"])

    return {
        "tool": "list_priority_actions",
        "total_actions": len(actions),
        "actions": actions[:20],
        "answer_type": "fact",
        "calculation_version": CALCULATION_VERSION,
    }


def list_records_blocking_reporting() -> dict[str, Any]:
    """Returns records that block the current reporting cycle close."""
    blocking = list_records(review_status="requires_attention")

    # Build a map of record_id → global open exceptions (catches exceptions that
    # were detected after initial record creation, e.g. pump_activity_without_meter_movement)
    global_exc_by_record: dict[str, list[dict]] = {}
    for exc in list_exceptions():
        if exc.get("status") != "resolved":
            rid = exc.get("record_id")
            if rid:
                global_exc_by_record.setdefault(rid, []).append(exc)

    summary = []
    for r in blocking:
        # Merge embedded exceptions with global exceptions for this record
        embedded = {e["id"]: e for e in r.get("exceptions", []) if e.get("status") != "resolved"}
        global_excs = {e["id"]: e for e in global_exc_by_record.get(r["id"], [])}
        merged = {**global_excs, **embedded}  # embedded takes precedence on collision
        open_excs = list(merged.values())
        summary.append({
            "record_id": r["id"],
            "well_id": r["well_id"],
            "reporting_period": r["reporting_period"],
            "blocking_reasons": [e["exception_type"] for e in open_excs],
            "exception_count": len(open_excs),
            "scenario_injected": r["scenario_injected"],
        })

    return {
        "tool": "list_records_blocking_reporting",
        "blocking_count": len(summary),
        "records": summary,
        "answer_type": "fact",
        "calculation_version": CALCULATION_VERSION,
    }


def generate_reporting_brief() -> dict[str, Any]:
    """Generates an executive reporting-readiness brief."""
    cycle = get_reporting_cycle_status()
    actions = list_priority_actions()
    blocking = list_records_blocking_reporting()
    assumptions = list_unvalidated_assumptions()

    top_actions = actions["actions"][:5]
    action_bullets = [
        f"{a['well_id']}: {a['exception_type'].replace('_', ' ')} — {a['recommended_action'][:80]}"
        for a in top_actions
    ]

    return {
        "tool": "generate_reporting_brief",
        "reporting_period": cycle["reporting_period"],
        "submission_deadline": cycle["submission_deadline"],
        "cycle_status": cycle["status_label"],
        "readiness_percentage": cycle["readiness_percentage"],
        "total_records": cycle["total_records"],
        "ready_for_export": cycle["ready_for_export"],
        "blocking_count": blocking["blocking_count"],
        "top_priority_actions": action_bullets,
        "unvalidated_assumption_count": assumptions["assumption_count"],
        "supported_extraction_af": cycle["supported_extraction_af"],
        "provisional_af": cycle["provisional_af"],
        "answer_type": "fact+calculation",
        "disclaimer": (
            "All figures are from demonstration scenarios. "
            "Not an official FCGMA reporting submission."
        ),
        "calculation_version": CALCULATION_VERSION,
    }


def generate_exception_packet() -> dict[str, Any]:
    """Generates an exception packet suitable for agency notification review."""
    exceptions = list_exceptions()
    open_excs = [e for e in exceptions if e.get("status") != "resolved"]

    by_type: dict[str, list[dict]] = {}
    for e in open_excs:
        by_type.setdefault(e["exception_type"], []).append(e)

    packet_items = []
    for exc_type, items in sorted(by_type.items()):
        packet_items.append({
            "exception_type": exc_type,
            "count": len(items),
            "rule_references": sorted({e.get("rule_id") for e in items if e.get("rule_id")}),
            "recommended_notification": _recommend_action(exc_type),
            "sample_detail": items[0]["detail"][:120] if items else "",
        })

    return {
        "tool": "generate_exception_packet",
        "total_exceptions": len(open_excs),
        "exception_types": len(by_type),
        "packet_items": packet_items,
        "disclaimer": (
            "This exception packet is generated from demonstration scenarios. "
            "AGRO-AI does not file regulatory reports. Review with FCGMA before any agency notification."
        ),
        "answer_type": "fact+recommended_next_action",
    }


def add_records_to_evidence_bundle(record_ids: list[str] | None = None) -> dict[str, Any]:
    """Stages records for inclusion in the evidence bundle."""
    if not record_ids:
        ready = list_records(review_status="ready_for_export")
        approved = list_records(review_status="reviewer_approved")
        record_ids = [r["id"] for r in ready + approved]

    added = []
    not_found = []
    for rid in record_ids:
        r = get_record(rid)
        if r:
            added.append({"record_id": rid, "well_id": r["well_id"], "review_status": r["review_status"]})
        else:
            not_found.append(rid)

    return {
        "tool": "add_records_to_evidence_bundle",
        "staged_count": len(added),
        "not_found_count": len(not_found),
        "staged_records": added,
        "note": (
            "Records staged for review. No records are modified — "
            "this is a selection only, not an approval or submission."
        ),
        "answer_type": "recommended_next_action",
    }


def draft_follow_up_request(exception_type: str | None = None) -> dict[str, Any]:
    """Drafts follow-up requests for agency notification or operator investigation."""
    records = list_records(review_status="requires_attention")
    items = []

    agency_types = {
        "unresolved_combcode", "multiplier_change", "meter_reset_detected",
        "backup_estimate_required", "late_arriving_record",
    }

    for r in records:
        open_excs = [
            e for e in r.get("exceptions", [])
            if e.get("status") != "resolved"
            and (exception_type is None or e["exception_type"] == exception_type)
        ]
        for e in open_excs:
            recipient = (
                "FCGMA (agency notification required)"
                if e["exception_type"] in agency_types
                else "Field operator (site investigation required)"
            )
            items.append({
                "well_id": r["well_id"],
                "record_id": r["id"],
                "exception_type": e["exception_type"],
                "detail": e["detail"],
                "rule_id": e.get("rule_id"),
                "follow_up_action": _recommend_action(e["exception_type"]),
                "follow_up_recipient": recipient,
            })

    return {
        "tool": "draft_follow_up_request",
        "item_count": len(items),
        "follow_up_items": items[:20],
        "filtered_by": exception_type,
        "disclaimer": (
            "Draft follow-up for review only. "
            "Terris does not file regulatory reports or claim legal compliance."
        ),
        "answer_type": "recommended_next_action",
    }


# ─────────────────────────────────────────────
# Extended tool map
# ─────────────────────────────────────────────

TERRIS_TOOL_MAP: dict[str, Any] = {
    **TOOL_MAP,
    "get_reporting_cycle_status": get_reporting_cycle_status,
    "list_priority_actions": list_priority_actions,
    "list_records_blocking_reporting": list_records_blocking_reporting,
    "generate_reporting_brief": generate_reporting_brief,
    "generate_exception_packet": generate_exception_packet,
    "add_records_to_evidence_bundle": add_records_to_evidence_bundle,
    "draft_follow_up_request": draft_follow_up_request,
}

TERRIS_PRESET_QUESTIONS = [
    {"key": "priority_actions", "label": "What requires my attention today?", "tool": "list_priority_actions"},
    {"key": "reporting_cycle", "label": "Where does the 2026-Q1 cycle stand?", "tool": "get_reporting_cycle_status"},
    {"key": "blocking_records", "label": "Which records are blocking reporting?", "tool": "list_records_blocking_reporting"},
    {"key": "reporting_brief", "label": "Generate a reporting-readiness brief.", "tool": "generate_reporting_brief"},
    {"key": "exception_packet", "label": "What exceptions require agency notification?", "tool": "generate_exception_packet"},
    {"key": "applied_water", "label": "How was applied-water attributed?", "tool": "run_applied_water_scenario"},
    {"key": "provider_health", "label": "Compare provider-feed health.", "tool": "compare_provider_health"},
    {"key": "data_gaps", "label": "What data would Fox Canyon need to provide?", "tool": "list_unvalidated_assumptions"},
    {"key": "follow_up", "label": "Draft operator follow-up requests.", "tool": "draft_follow_up_request"},
]


# ─────────────────────────────────────────────
# Intent classification
# ─────────────────────────────────────────────

INTENT_CATEGORIES: dict[str, list[str]] = {
    "review_queue": ["attention", "review", "priority", "requires", "action", "what needs", "blocking"],
    "reporting_cycle": ["reporting", "cycle", "deadline", "submission", "ready", "close", "2026-q", "readiness"],
    "exception_investigation": ["exception", "pump", "meter reset", "combcode", "duplicate", "gap", "reverse flow"],
    "applied_water": ["applied water", "attribution", "calculation", "provisional", "how calculated", " af "],
    "provider_health": ["provider", "health", "source", "connected", "wiseconn", "cimis", "ranch systems"],
    "data_gap": ["fox canyon", "data needed", "validation", "assumption", "what data", "refine"],
    "follow_up": ["follow up", "operator", "notify", "notification", "request", "agency"],
    "executive_summary": ["summary", "overview", "status", "how are we", "where do we"],
}


def classify_intent(query: str) -> str:
    q = query.lower()
    for intent, keywords in INTENT_CATEGORIES.items():
        if any(kw in q for kw in keywords):
            return intent
    return "executive_summary"


def _tools_for_intent(intent: str) -> list[str]:
    tool_map = {
        "review_queue": ["list_priority_actions", "list_records_blocking_reporting"],
        "reporting_cycle": ["get_reporting_cycle_status", "list_records_blocking_reporting"],
        "exception_investigation": ["generate_exception_packet", "list_priority_actions"],
        "applied_water": ["run_applied_water_scenario", "generate_reporting_summary"],
        "provider_health": ["compare_provider_health"],
        "data_gap": ["list_unvalidated_assumptions", "compare_provider_health"],
        "follow_up": ["draft_follow_up_request", "list_priority_actions"],
        "executive_summary": ["get_executive_summary", "get_reporting_cycle_status"],
    }
    return tool_map.get(intent, ["get_executive_summary"])


# ─────────────────────────────────────────────
# Pluralization helper
# ─────────────────────────────────────────────

def _n(count: int, singular: str, plural: str | None = None) -> str:
    """Return natural singular/plural: '1 record', '4 cases'. Never '(s)'."""
    pl = plural if plural is not None else singular + "s"
    return f"{count} {singular if count == 1 else pl}"


# ─────────────────────────────────────────────
# Natural-language stage labels shown to users
# ─────────────────────────────────────────────

STAGE_PROGRESS_LABELS: dict[str, str] = {
    "invoke_list_priority_actions": "Reviewing priority cases…",
    "invoke_get_reporting_cycle_status": "Reviewing the current reporting cycle…",
    "invoke_list_records_blocking_reporting": "Identifying records blocking cycle close…",
    "invoke_compare_provider_health": "Checking provider coverage and source health…",
    "invoke_run_applied_water_scenario": "Reconciling applied-water calculations…",
    "invoke_generate_exception_packet": "Compiling the exception packet…",
    "invoke_list_unvalidated_assumptions": "Reviewing governance assumptions…",
    "invoke_draft_follow_up_request": "Drafting follow-up requests…",
    "invoke_generate_reporting_brief": "Preparing reporting readiness brief…",
    "invoke_get_executive_summary": "Reviewing the ledger summary…",
    "invoke_generate_reporting_summary": "Checking reporting summary…",
    "invoke_add_records_to_evidence_bundle": "Staging evidence bundle…",
    "inspect_records": "Reconciling affected meter records…",
    "identify_assumptions": "Checking calculation assumptions…",
    "inspect_record": "Inspecting meter record…",
    "reconcile_calculations": "Verifying calculation lineage…",
    "inspect_lineage": "Reviewing source provenance…",
    "synthesize_answer": "Preparing a recommendation…",
}


def _user_stage_label(stage_name: str) -> str | None:
    """Return user-friendly label for a stage, or None to hide it."""
    hidden = {"classify_intent", "identify_tools", "llm_formatting", "synthesize_answer"}
    if stage_name in hidden:
        return None
    if stage_name.startswith("invoke_"):
        return STAGE_PROGRESS_LABELS.get(stage_name, "Gathering evidence…")
    return STAGE_PROGRESS_LABELS.get(stage_name)


# ─────────────────────────────────────────────
# Structured response builders
# ─────────────────────────────────────────────

def _brief_tool_result(tool_name: str, result: dict) -> str:
    if tool_name == "get_reporting_cycle_status":
        pct = result.get("readiness_percentage", 0)
        blocking = result.get("blocking_exceptions", 0)
        return f"Cycle: {result.get('status_label', '?')} · {pct}% ready · {_n(blocking, 'exception')} open"
    if tool_name == "list_priority_actions":
        n = result.get("total_actions", 0)
        return f"{_n(n, 'priority case')} requiring attention"
    if tool_name == "list_records_blocking_reporting":
        n = result.get("blocking_count", 0)
        return f"{_n(n, 'record')} blocking reporting cycle"
    if tool_name == "get_executive_summary":
        return (result.get("narrative", "") or "")[:120]
    if tool_name == "compare_provider_health":
        providers = result.get("providers", [])
        connected = sum(1 for p in providers if p["status"] == "connected")
        return f"{connected}/{len(providers)} providers connected"
    if tool_name == "generate_exception_packet":
        total = result.get("total_exceptions", 0)
        types = result.get("exception_types", 0)
        return f"{_n(total, 'exception')} across {_n(types, 'type')}"
    if tool_name == "run_applied_water_scenario":
        return f"{result.get('total_interval_af', 0):.2f} AF metered ({result.get('model_status', 'provisional')})"
    if tool_name == "list_unvalidated_assumptions":
        n = result.get("assumption_count", 0)
        return f"{_n(n, 'unvalidated assumption')}"
    if tool_name == "generate_reporting_summary":
        return f"Readiness: {result.get('reporting_readiness', '?')}"
    if tool_name == "generate_reporting_brief":
        pct = result.get("readiness_percentage", 0)
        n = result.get("blocking_count", 0)
        return f"{pct}% ready · {_n(n, 'case')} blocking"
    if tool_name == "draft_follow_up_request":
        n = result.get("item_count", 0)
        return f"{_n(n, 'follow-up request')} drafted"
    if tool_name == "add_records_to_evidence_bundle":
        n = result.get("staged_count", 0)
        return f"{_n(n, 'record')} staged for bundle"
    return "Tool completed"


def _build_direct_answer(primary_tool: str, primary_result: dict, all_results: dict) -> str:
    if primary_tool == "list_priority_actions":
        n = primary_result.get("total_actions", 0)
        if n == 0:
            return "No priority cases are currently open. All records are ready or pending review."
        actions = primary_result.get("actions", [])
        top = actions[:3]
        wells = ", ".join(a["well_id"] for a in top)
        return (
            f"{_n(n, 'priority case')} require attention. "
            f"Most urgent: {wells}."
        )

    if primary_tool == "get_reporting_cycle_status":
        pct = primary_result.get("readiness_percentage", 0)
        blocking = primary_result.get("blocking_exceptions", 0)
        status = primary_result.get("status_label", "")
        total = primary_result.get("total_records", 0)
        ready = primary_result.get("ready_for_export", 0)
        return (
            f"The 2026-Q1 reporting cycle is {status.lower()}. "
            f"{ready} of {total} records are cleared for reporting, "
            f"with {_n(blocking, 'open exception')} blocking cycle close."
        )

    if primary_tool == "list_records_blocking_reporting":
        n = primary_result.get("blocking_count", 0)
        if n == 0:
            return "No records are blocking the reporting cycle. All records are ready or approved."
        records = primary_result.get("records", [])
        wells = ", ".join(dict.fromkeys(r["well_id"] for r in records[:5]))
        return f"{_n(n, 'record')} are blocking the reporting cycle, affecting {wells}."

    if primary_tool == "generate_reporting_brief":
        pct = primary_result.get("readiness_percentage", 0)
        n = primary_result.get("blocking_count", 0)
        period = primary_result.get("reporting_period", "2026-Q1")
        deadline = primary_result.get("submission_deadline", "")
        return (
            f"{period} reporting brief: {primary_result.get('cycle_status', '').lower()}. "
            f"{pct}% of records are ready for export. "
            + (f"{_n(n, 'case')} blocking close. " if n else "")
            + (f"Submission deadline: {deadline}." if deadline else "")
        )

    if primary_tool == "get_executive_summary":
        return primary_result.get("narrative", "Ledger analysis complete. See evidence reviewed for details.")

    if primary_tool == "compare_provider_health":
        providers = primary_result.get("providers", [])
        disabled = [p for p in providers if p["status"] == "disabled"]
        unavail = [p for p in providers if p["status"] in ("unavailable", "pending_key")]
        if not disabled and not unavail:
            return "All configured providers are connected and operational."
        parts = []
        if disabled:
            parts.append(f"{_n(len(disabled), 'provider')} disabled (authorization pending)")
        if unavail:
            parts.append(f"{_n(len(unavail), 'provider')} unavailable (API key required)")
        return f"Provider coverage gaps: {'; '.join(parts)}."

    if primary_tool == "list_unvalidated_assumptions":
        n = primary_result.get("assumption_count", 0)
        return (
            f"{_n(n, 'assumption')} require Fox Canyon validation "
            "before the applied-water model can be confirmed."
        )

    if primary_tool == "generate_exception_packet":
        total = primary_result.get("total_exceptions", 0)
        types = primary_result.get("exception_types", 0)
        if total == 0:
            return "No open exceptions found. The dataset is clean."
        return (
            f"{_n(total, 'open exception')} across {_n(types, 'category')} "
            "require resolution before reporting."
        )

    if primary_tool == "run_applied_water_scenario":
        af = primary_result.get("total_interval_af", 0)
        prov = primary_result.get("provisional_records", 0)
        total = primary_result.get("total_meter_records", 0)
        return (
            f"Applied-water attribution (DEMO RULESET v0.1, provisional): "
            f"{af:.2f} AF metered across {_n(total, 'record')}. "
            + (f"{_n(prov, 'record')} remain provisional pending further validation." if prov else "")
        )

    if primary_tool == "draft_follow_up_request":
        n = primary_result.get("item_count", 0)
        return f"Drafted {_n(n, 'follow-up request')} for operator or agency notification."

    return "Investigation complete. See evidence trail for details."


def _build_why_it_matters(primary_tool: str, all_results: dict) -> str:
    if primary_tool in ("list_priority_actions", "list_records_blocking_reporting"):
        blocking = all_results.get("list_records_blocking_reporting", {}).get("blocking_count", 0)
        deadline = all_results.get("get_reporting_cycle_status", {}).get("submission_deadline", "")
        if blocking:
            return (
                f"{_n(blocking, 'record')} cannot be included in the reporting export until resolved. "
                + (f"Submission deadline: {deadline}. " if deadline else "")
                + "Unresolved records risk incomplete reporting."
            )
        return "Records are on track for the reporting cycle."

    if primary_tool == "get_reporting_cycle_status":
        return (
            "Groundwater extraction reporting requires complete, exception-free records. "
            "Records with open exceptions cannot be included in a reporting-ready export. "
            "Timely resolution is required to meet the FCGMA submission deadline."
        )

    if primary_tool == "compare_provider_health":
        return (
            "Provider health determines the quality and completeness of extraction evidence. "
            "Unavailable or disabled providers represent gaps in the water accounting record."
        )

    if primary_tool == "list_unvalidated_assumptions":
        return (
            "Unvalidated assumptions mean the applied-water model is provisional. "
            "Provisional calculations cannot be submitted as official reporting data "
            "until Fox Canyon validates the methodology."
        )

    if primary_tool == "run_applied_water_scenario":
        return (
            "Applied-water attribution connects groundwater extraction records to specific parcels. "
            "Provisional attribution cannot be used for regulatory reporting until the rule pack is validated."
        )

    return (
        "Complete, validated records are required for regulatory groundwater reporting. "
        "Unresolved exceptions block the reporting cycle."
    )


def _build_recommended_action(primary_tool: str, primary_result: dict, all_results: dict) -> str:
    if primary_tool == "list_priority_actions":
        actions = primary_result.get("actions", [])
        if not actions:
            return "No immediate action required. Continue monitoring for new exceptions."
        top = actions[0]
        return f"Begin with {top['well_id']}: {top['recommended_action'][:180]}."

    if primary_tool == "get_reporting_cycle_status":
        blocking = primary_result.get("requires_attention", 0)
        if blocking:
            return (
                f"Resolve {_n(blocking, 'blocking exception')} before the reporting cycle can close. "
                "Use the Action Queue to prioritize by exception type and severity."
            )
        return "Review and export the ready record set. No blocking exceptions remain."

    if primary_tool == "list_unvalidated_assumptions":
        return (
            "Request Fox Canyon's official CombCode mapping, applied-water attribution methodology, "
            "and pre-approved backup estimation procedure to replace the provisional demo ruleset."
        )

    if primary_tool == "compare_provider_health":
        providers = primary_result.get("providers", [])
        ranch = next((p for p in providers if "ranch" in p["provider_id"].lower()), None)
        if ranch and ranch["status"] == "disabled":
            return (
                "Request Ranch Systems official AMI export schema and API authorization. "
                "Without it, Ranch Systems records remain absent from the water accounting ledger."
            )
        return "Configure missing API keys to enable live data sources."

    if primary_tool == "draft_follow_up_request":
        return "Review the drafted requests. Submit agency notifications through official FCGMA channels."

    return "Review evidence in the Action Queue and resolve open exceptions before export."


def _build_remaining_uncertainty(all_results: dict) -> str:
    parts = []
    for tool_name, result in all_results.items():
        if tool_name == "list_unvalidated_assumptions":
            n = result.get("assumption_count", 0)
            if n:
                parts.append(f"{_n(n, 'unvalidated model assumption')}")
        if tool_name in ("list_priority_actions", "list_records_blocking_reporting"):
            n = result.get("total_actions") or result.get("blocking_count") or 0
            if n:
                parts.append(f"{_n(n, 'open exception')} pending resolution")
    if not parts:
        return "No significant uncertainties identified in the current dataset."
    return (
        " · ".join(parts)
        + " — all figures are provisional until Fox Canyon validates the applied-water model."
    )


def _build_available_actions(intent: str, all_results: dict) -> list[dict]:
    base = [
        {"action": "ask_terris", "label": "Ask Terris a follow-up", "target": "terris"},
        {"action": "view_action_queue", "label": "Open Action Queue", "target": "action_queue"},
        {"action": "generate_report", "label": "Generate Reporting Brief", "target": "reports"},
    ]
    if intent in ("review_queue", "exception_investigation"):
        base.insert(0, {"action": "resolve_exceptions", "label": "Resolve open exceptions", "target": "action_queue"})
    if intent == "reporting_cycle":
        base.insert(0, {"action": "generate_report", "label": "Generate Reporting Readiness Brief", "target": "reports"})
    return base[:4]


# ─────────────────────────────────────────────
# Deep investigation mode
# ─────────────────────────────────────────────

_DEEP_KEYWORDS = {
    "what is going on", "what's going on", "summary", "overview", "executive",
    "before the cycle", "cycle close", "risk of closing", "fastest path",
    "what would you focus", "what should we", "what changed", "since the last",
    "prepare", "generate", "draft", "brief", "report", "internal summary",
    "what happens if", "simulate", "if we clear", "resolve",
}

_DEEP_INTENTS = {"executive_summary", "reporting_cycle", "review_queue"}


def _is_deep_query(query: str, intent: str) -> bool:
    q = query.lower()
    return intent in _DEEP_INTENTS or any(kw in q for kw in _DEEP_KEYWORDS)


def _tools_for_deep_investigation(intent: str) -> list[str]:
    """Extended tool set for deep investigations — covers all major evidence areas."""
    base = _tools_for_intent(intent)
    extras = []
    if "get_reporting_cycle_status" not in base:
        extras.append("get_reporting_cycle_status")
    if "list_priority_actions" not in base:
        extras.append("list_priority_actions")
    if "list_records_blocking_reporting" not in base:
        extras.append("list_records_blocking_reporting")
    if "compare_provider_health" not in base:
        extras.append("compare_provider_health")
    if "list_unvalidated_assumptions" not in base:
        extras.append("list_unvalidated_assumptions")
    return base + extras


# ─────────────────────────────────────────────
# Main investigation runner
# ─────────────────────────────────────────────

def run_terris_investigation(
    query: str,
    record_id: str | None = None,
    tool_override: str | None = None,
    on_progress: Any | None = None,
) -> dict[str, Any]:
    """
    Run a complete Terris investigation.

    Returns a structured response with investigation stages (all real — based
    on tools actually invoked). LLM narration is handled by the conversation layer,
    not here — keeps this function pure deterministic.

    on_progress: optional callable(stage_name, user_label) called as each stage completes.
    """

    def _emit(stage_name: str, detail: str, status: str = "completed") -> None:
        label = _user_stage_label(stage_name)
        if on_progress and label:
            on_progress({"stage": stage_name, "label": label, "status": status})

    stages: list[dict[str, Any]] = []
    tool_results: dict[str, Any] = {}

    # ── Classify intent ──
    intent = classify_intent(query)
    stages.append({"stage": "classify_intent", "status": "completed",
                   "detail": f"Understood as: {intent.replace('_', ' ')}"})

    # ── Select tools ──
    deep = _is_deep_query(query, intent)
    if record_id:
        tools_to_run: list[str] = []
        stages.append({"stage": "identify_tools", "status": "completed",
                       "detail": f"Record-specific investigation: {record_id}"})
    elif tool_override:
        tools_to_run = [tool_override]
        stages.append({"stage": "identify_tools", "status": "completed",
                       "detail": f"Explicit tool: {tool_override}"})
    else:
        tools_to_run = _tools_for_deep_investigation(intent) if deep else _tools_for_intent(intent)
        stages.append({"stage": "identify_tools", "status": "completed",
                       "detail": f"{'Deep' if deep else 'Focused'} investigation: {len(tools_to_run)} tool(s)"})

    # ── Record-specific investigation ──
    if record_id:
        r = get_record(record_id)
        if r:
            _emit("inspect_record", f"Loaded {record_id}")
            stages.append({"stage": "inspect_record", "status": "completed",
                           "detail": f"Loaded {record_id}: {r['evidence_class']}, status={r['review_status']}"})
            explanation = get_calculation_explanation(r)
            _emit("reconcile_calculations", f"Verified {len(explanation.get('steps', []))} steps")
            stages.append({"stage": "reconcile_calculations", "status": "completed",
                           "detail": f"Verified {_n(len(explanation.get('steps', [])), 'calculation step')}"})
            _emit("inspect_lineage", f"Source: {r['provider']}")
            stages.append({"stage": "inspect_lineage", "status": "completed",
                           "detail": f"Source: {r['provider']} | Hash: {r['sanitized_source_hash']}"})
            open_excs = [e for e in r.get("exceptions", []) if e.get("status") != "resolved"]
            tool_results["explain_record"] = {
                "tool": "explain_record",
                "record_id": record_id,
                "evidence_class": r["evidence_class"],
                "provider": r["provider"],
                "sanitized_source_hash": r["sanitized_source_hash"],
                "event_timestamp": r["event_timestamp"],
                "reporting_period": r["reporting_period"],
                "review_status": r["review_status"],
                "interval_volume_af": r.get("interval_volume"),
                "open_exceptions": open_excs,
                "calculation_explanation": explanation,
                "scenario_injected": r["scenario_injected"],
                "scenario_label": r.get("scenario_label"),
                "answer_type": "fact+calculation",
            }
        else:
            stages.append({"stage": "inspect_record", "status": "failed",
                           "detail": f"Record {record_id} not found in ledger"})
            tool_results["error"] = {
                "tool": "explain_record",
                "answer_type": "missing_information",
                "message": f"Record '{record_id}' not found.",
            }

    else:
        # ── General investigation ──
        for tool_name in tools_to_run:
            fn = TERRIS_TOOL_MAP.get(tool_name)
            if fn is None:
                stages.append({"stage": f"invoke_{tool_name}", "status": "skipped",
                               "detail": f"Unknown tool: {tool_name}"})
                continue
            stage_key = f"invoke_{tool_name}"
            _emit(stage_key, tool_name)
            try:
                result = fn()
                tool_results[tool_name] = result
                brief = _brief_tool_result(tool_name, result)
                stages.append({"stage": stage_key, "status": "completed", "detail": brief})
            except Exception as exc:
                logger.exception("Terris tool %s failed: %s", tool_name, exc)
                stages.append({"stage": stage_key, "status": "failed", "detail": str(exc)[:120]})

        # ── Summary of records reviewed ──
        records_reviewed = sum(
            r.get("total_records") or r.get("count") or r.get("total_actions") or 0
            for r in tool_results.values()
        )
        if records_reviewed:
            _emit("inspect_records", f"Reviewed {records_reviewed} items")
            stages.append({"stage": "inspect_records", "status": "completed",
                           "detail": f"Reviewed {_n(records_reviewed, 'item')} across tool results"})

        # ── Assumption scan ──
        if "list_unvalidated_assumptions" not in tool_results and intent in (
            "reporting_cycle", "applied_water", "executive_summary"
        ):
            _emit("identify_assumptions", "checking assumptions")
            assump = list_unvalidated_assumptions()
            tool_results["list_unvalidated_assumptions"] = assump
            n_assump = assump.get("assumption_count", 0)
            stages.append({"stage": "identify_assumptions", "status": "completed",
                           "detail": f"{_n(n_assump, 'unvalidated assumption')} noted"})

    # ── Synthesize ──
    _emit("synthesize_answer", "synthesis")
    stages.append({"stage": "synthesize_answer", "status": "completed",
                   "detail": f"Built response from {len(tool_results)} tool result(s)"})

    # Build structured sections
    primary_tool = next(iter(tool_results), "get_executive_summary")
    primary_result = tool_results.get(primary_tool, {})

    direct_answer = _build_direct_answer(primary_tool, primary_result, tool_results)
    why_it_matters = _build_why_it_matters(primary_tool, tool_results)
    recommended_action = _build_recommended_action(primary_tool, primary_result, tool_results)
    remaining_uncertainty = _build_remaining_uncertainty(tool_results)
    available_actions = _build_available_actions(intent, tool_results)

    # Build evidence trail with user-friendly labels (no raw tool names in main trail)
    evidence_reviewed = [
        {
            "tool": tn,
            "summary": _brief_tool_result(tn, tr),
            "user_label": STAGE_PROGRESS_LABELS.get(f"invoke_{tn}", tn.replace("_", " ").title()),
        }
        for tn, tr in tool_results.items()
    ]

    # Count reviewed items for "Reviewed X records · Y cases · Z providers"
    total_records = tool_results.get("get_reporting_cycle_status", {}).get("total_records", 0)
    total_cases = len(tool_results.get("list_priority_actions", {}).get("actions", []))
    providers = tool_results.get("compare_provider_health", {}).get("providers", [])
    gov_refs = tool_results.get("list_unvalidated_assumptions", {}).get("assumption_count", 0)

    reviewed_summary_parts = []
    if total_records:
        reviewed_summary_parts.append(_n(total_records, "record"))
    if total_cases:
        reviewed_summary_parts.append(_n(total_cases, "case"))
    if providers:
        reviewed_summary_parts.append(_n(len(providers), "provider"))
    if gov_refs:
        reviewed_summary_parts.append(_n(gov_refs, "governance reference"))
    reviewed_summary = " · ".join(reviewed_summary_parts) if reviewed_summary_parts else ""

    # User-visible investigation progress labels (no internal names)
    progress_labels = [
        _user_stage_label(s["stage"])
        for s in stages
        if _user_stage_label(s["stage"]) and s["status"] == "completed"
    ]

    answer_type = primary_result.get("answer_type", "fact") if tool_results else "missing_information"

    return {
        "agent": AGENT_NAME,
        "query": query,
        "intent": intent,
        "investigation_stages": stages,
        "progress_labels": progress_labels,
        "reviewed_summary": reviewed_summary,
        "direct_answer": direct_answer,
        "why_it_matters": why_it_matters,
        "evidence_reviewed": evidence_reviewed,
        "recommended_action": recommended_action,
        "remaining_uncertainty": remaining_uncertainty,
        "available_actions": available_actions,
        "tool_results": tool_results,
        "answer_type": answer_type,
        "calculation_version": CALCULATION_VERSION,
        "disclaimer": (
            "Terris answers are grounded in deterministic backend tools and source records. "
            "Terris does not approve records, file reports, or claim legal compliance. "
            "All quantities are from demonstration scenarios only."
        ),
    }
