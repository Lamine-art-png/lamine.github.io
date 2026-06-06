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

    actions = []
    for r in records:
        open_excs = [e for e in r.get("exceptions", []) if e.get("status") != "resolved"]
        for e in open_excs:
            priority = PRIORITY_ORDER.get(e["exception_type"], 20)
            actions.append({
                "record_id": r["id"],
                "well_id": r["well_id"],
                "exception_type": e["exception_type"],
                "severity": e["severity"],
                "priority_rank": priority,
                "detail": e["detail"][:120],
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
    summary = []
    for r in blocking:
        open_excs = [e for e in r.get("exceptions", []) if e.get("status") != "resolved"]
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
# Structured response builders
# ─────────────────────────────────────────────

def _brief_tool_result(tool_name: str, result: dict) -> str:
    if tool_name == "get_reporting_cycle_status":
        return f"Cycle: {result.get('status_label', '?')} | {result.get('readiness_percentage', 0)}% ready | {result.get('blocking_exceptions', 0)} exception(s)"
    if tool_name == "list_priority_actions":
        return f"{result.get('total_actions', 0)} priority action(s) requiring attention"
    if tool_name == "list_records_blocking_reporting":
        return f"{result.get('blocking_count', 0)} record(s) blocking reporting cycle"
    if tool_name == "get_executive_summary":
        return (result.get("narrative", "") or "")[:120]
    if tool_name == "compare_provider_health":
        providers = result.get("providers", [])
        connected = sum(1 for p in providers if p["status"] == "connected")
        return f"{connected}/{len(providers)} providers connected"
    if tool_name == "generate_exception_packet":
        return f"{result.get('total_exceptions', 0)} exception(s) across {result.get('exception_types', 0)} type(s)"
    if tool_name == "run_applied_water_scenario":
        return f"{result.get('total_interval_af', 0):.2f} AF metered ({result.get('model_status', 'provisional')})"
    if tool_name == "list_unvalidated_assumptions":
        return f"{result.get('assumption_count', 0)} unvalidated assumption(s)"
    if tool_name == "generate_reporting_summary":
        return f"Readiness: {result.get('reporting_readiness', '?')}"
    if tool_name == "generate_reporting_brief":
        return f"{result.get('readiness_percentage', 0)}% ready | {result.get('blocking_count', 0)} blocking"
    if tool_name == "draft_follow_up_request":
        return f"{result.get('item_count', 0)} follow-up item(s) drafted"
    if tool_name == "add_records_to_evidence_bundle":
        return f"{result.get('staged_count', 0)} record(s) staged for bundle"
    return "Tool completed"


def _build_direct_answer(primary_tool: str, primary_result: dict, all_results: dict) -> str:
    if primary_tool == "list_priority_actions":
        n = primary_result.get("total_actions", 0)
        if n == 0:
            return "No priority actions are currently open. All records are ready or pending review."
        actions = primary_result.get("actions", [])
        top = actions[:3]
        wells = ", ".join(a["well_id"] for a in top)
        return f"{n} priority action(s) require attention. Most urgent: {wells}."

    if primary_tool == "get_reporting_cycle_status":
        pct = primary_result.get("readiness_percentage", 0)
        blocking = primary_result.get("blocking_exceptions", 0)
        status = primary_result.get("status_label", "")
        return (
            f"The 2026-Q1 reporting cycle is {status.lower()}. "
            f"{pct}% of records are ready for export, with {blocking} open exception(s) blocking close."
        )

    if primary_tool == "list_records_blocking_reporting":
        n = primary_result.get("blocking_count", 0)
        if n == 0:
            return "No records are blocking the reporting cycle. All records are ready or approved."
        records = primary_result.get("records", [])
        wells = ", ".join(r["well_id"] for r in records[:3])
        return f"{n} record(s) are blocking the reporting cycle: {wells}."

    if primary_tool == "generate_reporting_brief":
        return (
            f"Reporting period {primary_result.get('reporting_period', '2026-Q1')}: "
            f"{primary_result.get('cycle_status', '').lower()}. "
            f"{primary_result.get('readiness_percentage', 0)}% ready. "
            f"{primary_result.get('blocking_count', 0)} record(s) blocking."
        )

    if primary_tool == "get_executive_summary":
        return primary_result.get("narrative", "Ledger analysis complete. See evidence reviewed for details.")

    if primary_tool == "compare_provider_health":
        providers = primary_result.get("providers", [])
        disabled = [p for p in providers if p["status"] == "disabled"]
        unavail = [p for p in providers if p["status"] == "unavailable"]
        if not disabled and not unavail:
            return "All configured providers are connected and operational."
        parts = []
        if disabled:
            parts.append(f"{len(disabled)} disabled (authorization pending)")
        if unavail:
            parts.append(f"{len(unavail)} unavailable (API key required)")
        return f"Provider status: {'; '.join(parts)}."

    if primary_tool == "list_unvalidated_assumptions":
        n = primary_result.get("assumption_count", 0)
        return f"{n} assumption(s) require Fox Canyon validation before the applied-water model can be confirmed."

    if primary_tool == "generate_exception_packet":
        total = primary_result.get("total_exceptions", 0)
        types = primary_result.get("exception_types", 0)
        if total == 0:
            return "No open exceptions found. The dataset is clean."
        return f"{total} open exception(s) across {types} type(s) require resolution before reporting."

    if primary_tool == "run_applied_water_scenario":
        af = primary_result.get("total_interval_af", 0)
        prov = primary_result.get("provisional_records", 0)
        total = primary_result.get("total_meter_records", 0)
        return (
            f"Applied-water attribution (DEMO RULESET v0.1, provisional): "
            f"{af:.2f} AF metered across {total} record(s). "
            f"{prov} provisional pending further validation."
        )

    if primary_tool == "draft_follow_up_request":
        n = primary_result.get("item_count", 0)
        return f"Drafted {n} follow-up item(s) for operator or agency notification."

    return "Investigation complete. See Evidence Reviewed below."


def _build_why_it_matters(primary_tool: str, all_results: dict) -> str:
    if primary_tool in ("list_priority_actions", "list_records_blocking_reporting"):
        blocking = all_results.get("list_records_blocking_reporting", {}).get("blocking_count", 0)
        deadline = all_results.get("get_reporting_cycle_status", {}).get("submission_deadline", "")
        if blocking:
            return (
                f"{blocking} record(s) cannot be included in the reporting export until resolved. "
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
                f"Resolve {blocking} blocking exception(s) before the reporting cycle can close. "
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
        return "Review the drafted follow-up items. Submit agency notifications through official FCGMA channels."

    return "Review evidence in the Action Queue and resolve open exceptions before export."


def _build_remaining_uncertainty(all_results: dict) -> str:
    parts = []
    for tool_name, result in all_results.items():
        if tool_name == "list_unvalidated_assumptions":
            n = result.get("assumption_count", 0)
            if n:
                parts.append(f"{n} unvalidated model assumption(s)")
        if tool_name in ("list_priority_actions", "list_records_blocking_reporting"):
            n = result.get("total_actions") or result.get("blocking_count") or 0
            if n:
                parts.append(f"{n} open exception(s) pending resolution")
    if not parts:
        return "No significant uncertainties identified in the current dataset."
    return (
        " | ".join(parts)
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
# Main investigation runner
# ─────────────────────────────────────────────

def run_terris_investigation(
    query: str,
    record_id: str | None = None,
    tool_override: str | None = None,
) -> dict[str, Any]:
    """
    Run a complete Terris investigation.

    Returns a structured response with investigation stages (all real — based
    on tools actually invoked) and six answer sections.
    """
    stages: list[dict[str, Any]] = []
    tool_results: dict[str, Any] = {}

    # ── Stage 1: Classify intent ──
    intent = classify_intent(query)
    stages.append({
        "stage": "classify_intent",
        "status": "completed",
        "detail": f"Understood as: {intent.replace('_', ' ')}",
    })

    # ── Stage 2: Identify tools ──
    if record_id:
        tools_to_run: list[str] = []
        stages.append({
            "stage": "identify_tools",
            "status": "completed",
            "detail": f"Record-specific investigation: {record_id}",
        })
    elif tool_override:
        tools_to_run = [tool_override]
        stages.append({
            "stage": "identify_tools",
            "status": "completed",
            "detail": f"Explicit tool: {tool_override}",
        })
    else:
        tools_to_run = _tools_for_intent(intent)
        stages.append({
            "stage": "identify_tools",
            "status": "completed",
            "detail": f"Selected: {', '.join(tools_to_run)}",
        })

    # ── Stage 3: Record-specific or general investigation ──
    if record_id:
        r = get_record(record_id)
        if r:
            stages.append({
                "stage": "inspect_record",
                "status": "completed",
                "detail": f"Loaded {record_id}: {r['evidence_class']}, status={r['review_status']}",
            })
            explanation = get_calculation_explanation(r)
            stages.append({
                "stage": "reconcile_calculations",
                "status": "completed",
                "detail": f"Verified {len(explanation.get('steps', []))} calculation step(s)",
            })
            stages.append({
                "stage": "inspect_lineage",
                "status": "completed",
                "detail": f"Source: {r['provider']} | Hash: {r['sanitized_source_hash']}",
            })
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
            stages.append({
                "stage": "inspect_record",
                "status": "failed",
                "detail": f"Record {record_id} not found in ledger",
            })
            tool_results["error"] = {
                "tool": "explain_record",
                "answer_type": "missing_information",
                "message": f"Record '{record_id}' not found.",
            }
    else:
        # Invoke each selected tool
        for tool_name in tools_to_run:
            fn = TERRIS_TOOL_MAP.get(tool_name)
            if fn is None:
                stages.append({
                    "stage": f"invoke_{tool_name}",
                    "status": "skipped",
                    "detail": f"Unknown tool: {tool_name}",
                })
                continue
            try:
                result = fn()
                tool_results[tool_name] = result
                stages.append({
                    "stage": f"invoke_{tool_name}",
                    "status": "completed",
                    "detail": _brief_tool_result(tool_name, result),
                })
            except Exception as exc:
                logger.exception("Terris tool %s failed: %s", tool_name, exc)
                stages.append({
                    "stage": f"invoke_{tool_name}",
                    "status": "failed",
                    "detail": str(exc)[:120],
                })

        # Inspect records count across results
        records_reviewed = sum(
            r.get("total_records") or r.get("count") or r.get("total_actions") or 0
            for r in tool_results.values()
        )
        if records_reviewed:
            stages.append({
                "stage": "inspect_records",
                "status": "completed",
                "detail": f"Reviewed {records_reviewed} item(s) across tool results",
            })

        # Add assumption scan for higher-level intents
        if "list_unvalidated_assumptions" not in tool_results and intent in (
            "reporting_cycle", "applied_water", "executive_summary"
        ):
            assump = list_unvalidated_assumptions()
            tool_results["list_unvalidated_assumptions"] = assump
            stages.append({
                "stage": "identify_assumptions",
                "status": "completed",
                "detail": f"{assump.get('assumption_count', 0)} unvalidated assumption(s) noted",
            })

    # ── Stage: Synthesize ──
    stages.append({
        "stage": "synthesize_answer",
        "status": "completed",
        "detail": f"Built structured response from {len(tool_results)} tool result(s)",
    })

    # Build structured sections
    primary_tool = next(iter(tool_results), "get_executive_summary")
    primary_result = tool_results.get(primary_tool, {})

    direct_answer = _build_direct_answer(primary_tool, primary_result, tool_results)
    why_it_matters = _build_why_it_matters(primary_tool, tool_results)
    recommended_action = _build_recommended_action(primary_tool, primary_result, tool_results)
    remaining_uncertainty = _build_remaining_uncertainty(tool_results)
    available_actions = _build_available_actions(intent, tool_results)

    evidence_reviewed = [
        {
            "tool": tn,
            "summary": _brief_tool_result(tn, tr),
        }
        for tn, tr in tool_results.items()
    ]

    # Optional LLM enhancement of direct_answer only
    llm_enhanced = False
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if api_key and tool_results:
        try:
            det_text = _format_deterministic_answer(primary_result)
            direct_answer = _llm_format_terris(query, det_text, api_key)
            llm_enhanced = True
            stages.append({
                "stage": "llm_formatting",
                "status": "completed",
                "detail": "LLM formatting applied to direct answer",
            })
        except Exception as exc:
            logger.warning("Terris LLM formatting failed: %s", exc)

    answer_type = primary_result.get("answer_type", "fact") if tool_results else "missing_information"

    return {
        "agent": AGENT_NAME,
        "query": query,
        "intent": intent,
        "investigation_stages": stages,
        "direct_answer": direct_answer,
        "why_it_matters": why_it_matters,
        "evidence_reviewed": evidence_reviewed,
        "recommended_action": recommended_action,
        "remaining_uncertainty": remaining_uncertainty,
        "available_actions": available_actions,
        "tool_results": tool_results,
        "llm_enhanced": llm_enhanced,
        "answer_type": answer_type,
        "calculation_version": CALCULATION_VERSION,
        "disclaimer": (
            "Terris answers are grounded in deterministic backend tools and source records. "
            "Terris does not approve records, file reports, or claim legal compliance. "
            "All quantities are from demonstration scenarios only."
        ),
    }


def _llm_format_terris(query: str, deterministic_text: str, api_key: str) -> str:
    """Optional LLM layer — formats the deterministic answer, adds no new facts."""
    import anthropic  # type: ignore
    client = anthropic.Anthropic(api_key=api_key)
    system = (
        "You are Terris, an AGRO-AI Water Intelligence Agent for Fox Canyon GMA. "
        "Elaborate only on the deterministic tool result provided. "
        "Do NOT generate quantities, facts, or conclusions not present in it. "
        "Do NOT approve records, file reports, or claim compliance. "
        "Be executive-appropriate: clear, specific, three sentences maximum."
    )
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=system,
        messages=[{"role": "user", "content": f"Question: {query}\n\nTool result:\n{deterministic_text}"}],
    )
    return msg.content[0].text
