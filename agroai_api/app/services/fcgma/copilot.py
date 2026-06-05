"""Grounded AI Copilot for the FCGMA Water Intelligence Copilot.

All answers are grounded in deterministic backend tools.
The LLM (if configured) may format and elaborate answers, but must not
generate quantities, facts, or conclusions beyond what the tools return.

If no LLM key is configured, the deterministic fallback produces complete,
useful answers for all preset questions.

AI CONSTRAINTS:
- Must cite record IDs, calculation versions, source hashes
- Must not approve records, file reports, or claim legal compliance
- Must not generate unsupported quantities
- Must distinguish: fact, calculation, provisional inference, missing info, recommended action
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
from .rule_pack import PACK_METADATA, get_rules

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Deterministic tool implementations
# ─────────────────────────────────────────────

def get_executive_summary() -> dict[str, Any]:
    stats = ledger_stats()
    records = list_records()
    exceptions = list_exceptions()

    open_exceptions = [e for e in exceptions if e.get("status") != "resolved"]
    exc_types: dict[str, int] = {}
    for e in open_exceptions:
        t = e["exception_type"]
        exc_types[t] = exc_types.get(t, 0) + 1

    requires_attention = [r for r in records if r["review_status"] == "requires_attention"]
    ready = [r for r in records if r["review_status"] in ("ready_for_export", "reviewer_approved")]

    # Build narrative
    bullets = []
    if exc_types.get("missing_telemetry_interval"):
        bullets.append(f"{exc_types['missing_telemetry_interval']} source(s) contain a telemetry gap during confirmed pump activity")
    if exc_types.get("meter_reset_detected"):
        bullets.append(f"{exc_types['meter_reset_detected']} record(s) contain a likely meter reset")
    if exc_types.get("unresolved_combcode"):
        bullets.append(f"{exc_types['unresolved_combcode']} record(s) are missing a confirmed CombCode mapping")
    if exc_types.get("duplicate_record"):
        bullets.append(f"{exc_types['duplicate_record']} duplicate record(s) detected")
    if exc_types.get("pump_activity_without_meter_movement"):
        bullets.append(f"{exc_types['pump_activity_without_meter_movement']} record(s) show pump activity without corresponding meter movement")
    if exc_types.get("backup_estimate_required"):
        bullets.append(f"{exc_types['backup_estimate_required']} record(s) require backup estimation due to meter failure")

    if bullets:
        narrative = (
            f"AGRO-AI identified {len(requires_attention)} record(s) requiring attention. "
            + "; ".join(bullets[:3])
            + (". Review is required before affected records can be included in a reporting-ready export." if bullets else "")
        )
    elif ready:
        narrative = f"All {len(ready)} reviewed record(s) are ready for export. No open exceptions detected."
    else:
        narrative = "No records loaded. Inject demonstration scenarios or import AMI CSV data to begin."

    return {
        "tool": "get_executive_summary",
        "narrative": narrative,
        "stats": stats,
        "requires_attention_count": len(requires_attention),
        "ready_count": len(ready),
        "open_exception_count": len(open_exceptions),
        "exception_type_breakdown": exc_types,
        "calculation_version": CALCULATION_VERSION,
        "answer_type": "fact+calculation",
        "caveats": [
            "Statistics are computed from demonstration scenarios only.",
            "No live Fox Canyon data is connected.",
        ],
    }


def list_records_requiring_attention() -> dict[str, Any]:
    records = list_records(review_status="requires_attention")
    summary = []
    for r in records:
        summary.append({
            "record_id": r["id"],
            "well_id": r["well_id"],
            "meter_id": r["meter_id"],
            "evidence_class": r["evidence_class"],
            "provider": r["provider"],
            "event_timestamp": r["event_timestamp"],
            "reporting_period": r["reporting_period"],
            "open_exceptions": [
                e for e in r.get("exceptions", []) if e.get("status") != "resolved"
            ],
            "scenario_injected": r["scenario_injected"],
            "scenario_label": r["scenario_label"],
        })

    return {
        "tool": "list_records_requiring_attention",
        "count": len(summary),
        "records": summary,
        "answer_type": "fact",
        "calculation_version": CALCULATION_VERSION,
    }


def explain_record(record_id: str) -> dict[str, Any]:
    record = get_record(record_id)
    if not record:
        return {
            "tool": "explain_record",
            "answer_type": "missing_information",
            "message": f"Record '{record_id}' not found in the ledger.",
        }

    explanation = get_calculation_explanation(record)
    open_excs = [e for e in record.get("exceptions", []) if e.get("status") != "resolved"]

    why_provisional = []
    if not record.get("combcode"):
        why_provisional.append("CombCode not resolved — cannot confirm management zone assignment.")
    if not record.get("parcel_ids"):
        why_provisional.append("Parcel mapping not confirmed.")
    if open_excs:
        why_provisional.append(f"{len(open_excs)} open exception(s) require review.")
    if record.get("scenario_injected"):
        why_provisional.append("This is a demonstration scenario — not authorized field data.")

    return {
        "tool": "explain_record",
        "record_id": record_id,
        "evidence_class": record["evidence_class"],
        "provider": record["provider"],
        "sanitized_source_hash": record["sanitized_source_hash"],
        "event_timestamp": record["event_timestamp"],
        "reporting_period": record["reporting_period"],
        "review_status": record["review_status"],
        "interval_volume_af": record.get("interval_volume"),
        "attribution_provisional": record.get("attribution_provisional"),
        "open_exceptions": open_excs,
        "why_provisional": why_provisional,
        "calculation_explanation": explanation,
        "scenario_injected": record["scenario_injected"],
        "scenario_label": record.get("scenario_label"),
        "answer_type": "fact+calculation+provisional_inference",
        "calculation_version": CALCULATION_VERSION,
    }


def get_water_ledger(record_id: str) -> dict[str, Any]:
    record = get_record(record_id)
    if not record:
        return {
            "tool": "get_water_ledger",
            "answer_type": "missing_information",
            "message": f"Record '{record_id}' not found.",
        }
    return {
        "tool": "get_water_ledger",
        "record": record,
        "answer_type": "fact",
        "calculation_version": CALCULATION_VERSION,
    }


def compare_provider_health() -> dict[str, Any]:
    import os
    health: list[dict[str, Any]] = []

    for key, reg in PROVIDER_REGISTRY.items():
        missing_env = [e for e in reg["requires_env"] if not os.getenv(e, "").strip()]
        if reg["status"] == "disabled":
            status = "disabled"
            message = reg.get("note", "Disabled.")
        elif missing_env:
            status = "unavailable"
            message = f"Live source unavailable — configure authorized access. Missing env: {', '.join(missing_env)}"
        else:
            status = "connected"
            message = "Adapter configured."

        # Count records from this provider
        provider_records = list_records(provider=key)
        health.append({
            "provider_id": key,
            "label": reg["label"],
            "status": status,
            "message": message,
            "record_count": len(provider_records),
            "evidence_class": reg["evidence_class"],
            "note": reg.get("note"),
        })

    return {
        "tool": "compare_provider_health",
        "providers": health,
        "answer_type": "fact",
    }


def show_data_lineage(record_id: str) -> dict[str, Any]:
    record = get_record(record_id)
    if not record:
        return {
            "tool": "show_data_lineage",
            "answer_type": "missing_information",
            "message": f"Record '{record_id}' not found.",
        }
    return {
        "tool": "show_data_lineage",
        "record_id": record_id,
        "evidence_class": record["evidence_class"],
        "provider": record["provider"],
        "sanitized_source_hash": record["sanitized_source_hash"],
        "source_lineage": record["source_lineage"],
        "audit_events": record.get("audit_events", []),
        "scenario_injected": record["scenario_injected"],
        "scenario_label": record.get("scenario_label"),
        "calculation_version": CALCULATION_VERSION,
        "answer_type": "fact",
    }


def list_unvalidated_assumptions() -> dict[str, Any]:
    rules = get_rules()
    unvalidated = [r for r in rules if r.get("validation_required")]
    records = list_records()

    assumptions = [
        {
            "assumption_id": "assump-001",
            "category": "applied_water_model",
            "description": "Applied-water attribution ruleset (DEMO RULESET v0.1) is provisional and requires Fox Canyon validation.",
            "status": "unvalidated",
            "what_to_request": "Fox Canyon's official applied-water attribution methodology and CombCode mapping logic.",
        },
        {
            "assumption_id": "assump-002",
            "category": "meter_failure_backup",
            "description": "Backup estimation methodology for meter failures requires Fox Canyon pre-approval.",
            "status": "unvalidated",
            "what_to_request": "FCGMA-approved backup estimation procedure and form references.",
        },
        {
            "assumption_id": "assump-003",
            "category": "combcode_mapping",
            "description": "CombCode assignments for demonstration wells are illustrative. Real CombCode mapping requires FCGMA data.",
            "status": "unvalidated",
            "what_to_request": "Official CombCode lookup table or direct confirmation from FCGMA for each well.",
        },
        {
            "assumption_id": "assump-004",
            "category": "ranch_systems",
            "description": "Ranch Systems adapter is pending official schema and API authorization.",
            "status": "disabled",
            "what_to_request": "Official Ranch Systems AMI export schema, sample file, or API authorization.",
        },
    ]

    return {
        "tool": "list_unvalidated_assumptions",
        "assumption_count": len(assumptions),
        "assumptions": assumptions,
        "unvalidated_rule_count": len(unvalidated),
        "answer_type": "provisional_inference+missing_information",
        "recommended_next_action": (
            "Request Fox Canyon's official CombCode mapping, applied-water attribution methodology, "
            "and pre-approved backup estimation procedure to replace provisional demo ruleset."
        ),
    }


def run_applied_water_scenario() -> dict[str, Any]:
    meter_records = list_records(evidence_class="groundwater_meter_reading")
    total_interval_af = sum(
        r.get("interval_volume") or 0
        for r in meter_records
        if r.get("interval_volume") is not None
    )
    provisional_records = [r for r in meter_records if r.get("attribution_provisional")]
    confirmed_records = [r for r in meter_records if not r.get("attribution_provisional") and r.get("interval_volume")]

    return {
        "tool": "run_applied_water_scenario",
        "applied_water_model": "DEMO RULESET v0.1",
        "model_status": "provisional",
        "model_requires_validation": True,
        "total_meter_records": len(meter_records),
        "provisional_records": len(provisional_records),
        "confirmed_records": len(confirmed_records),
        "total_interval_af": round(total_interval_af, 4),
        "disclaimer": (
            "All quantities are provisional demonstration calculations. "
            "The applied-water model requires Fox Canyon validation before operational use."
        ),
        "answer_type": "provisional_inference",
        "calculation_version": CALCULATION_VERSION,
    }


def generate_reporting_summary() -> dict[str, Any]:
    stats = ledger_stats()
    records = list_records()
    exceptions = list_exceptions()
    open_excs = [e for e in exceptions if e.get("status") != "resolved"]

    provider_breakdown: dict[str, int] = {}
    for r in records:
        p = r["provider"]
        provider_breakdown[p] = provider_breakdown.get(p, 0) + 1

    return {
        "tool": "generate_reporting_summary",
        "reporting_period": "2026-Q1",
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "total_records": stats["total_records"],
        "ready_for_export": stats["ready_for_export"],
        "requires_attention": stats["requires_attention"],
        "open_exceptions": len(open_excs),
        "supported_extraction_af": stats["supported_extraction_af"],
        "provisional_af": stats["provisional_af"],
        "provider_breakdown": provider_breakdown,
        "evidence_class_breakdown": stats["evidence_class_breakdown"],
        "reporting_readiness": "NOT ready" if open_excs else "Ready for review",
        "disclaimer": (
            "This summary is generated from demonstration scenarios only. "
            "No authorized Fox Canyon extraction data is included. "
            "Not an official FCGMA reporting submission."
        ),
        "answer_type": "fact+calculation",
        "calculation_version": CALCULATION_VERSION,
    }


def generate_exception_report() -> dict[str, Any]:
    exceptions = list_exceptions()
    open_excs = [e for e in exceptions if e.get("status") != "resolved"]
    by_type: dict[str, list[dict[str, Any]]] = {}
    for e in open_excs:
        t = e["exception_type"]
        by_type.setdefault(t, []).append(e)

    return {
        "tool": "generate_exception_report",
        "total_open_exceptions": len(open_excs),
        "by_type": {k: len(v) for k, v in by_type.items()},
        "exceptions": open_excs[:50],
        "answer_type": "fact",
    }


def draft_operator_follow_up() -> dict[str, Any]:
    records = list_records(review_status="requires_attention")
    items = []
    for r in records:
        open_excs = [e for e in r.get("exceptions", []) if e.get("status") != "resolved"]
        for e in open_excs:
            items.append({
                "well_id": r["well_id"],
                "meter_id": r["meter_id"],
                "exception_type": e["exception_type"],
                "detail": e["detail"],
                "rule_id": e.get("rule_id"),
                "recommended_action": _recommend_action(e["exception_type"]),
            })

    return {
        "tool": "draft_operator_follow_up",
        "item_count": len(items),
        "follow_up_items": items[:20],
        "disclaimer": (
            "This is a draft follow-up list for review purposes only. "
            "AGRO-AI does not approve records, file regulatory reports, or confirm compliance."
        ),
        "answer_type": "recommended_next_action",
    }


def _recommend_action(exception_type: str) -> str:
    actions = {
        "meter_reset_detected": "Notify FCGMA of meter replacement. Provide previous and new meter readings, replacement date, and new meter serial number using FCGMA agency forms.",
        "missing_telemetry_interval": "Investigate data transmission failure for the gap period. If extraction occurred, determine if backup estimation is required under FCGMA procedure.",
        "multiplier_change": "Notify FCGMA of multiplier change using the appropriate agency form. Verify all affected records use the correct multiplier.",
        "unit_change": "Confirm the correct unit for this meter with the operator. Verify conversion factor is appropriate for this meter model.",
        "duplicate_record": "Identify which record is authoritative and exclude the duplicate from extraction totals.",
        "pump_activity_without_meter_movement": "Inspect meter for malfunction. If extraction occurred during pump activity, backup estimation may be required.",
        "reverse_flow": "Investigate cause of negative flow reading. Check for meter malfunction, data error, or flow direction change.",
        "unresolved_combcode": "Contact FCGMA to obtain the correct CombCode for this well.",
        "unresolved_parcel_mapping": "Confirm well-to-parcel mapping with the operator and FCGMA.",
        "backup_estimate_required": "Apply FCGMA-approved backup estimation procedure. Document methodology and submit with reporting package.",
        "late_arriving_record": "Confirm correct reporting period assignment. Update prior-period totals if needed.",
        "negative_delta": "Investigate cause of negative cumulative delta. Check for meter reset, reverse flow, or data error.",
    }
    return actions.get(exception_type, "Review this exception with the operator and FCGMA before export.")


# ─────────────────────────────────────────────
# Dispatch — maps questions to tools
# ─────────────────────────────────────────────

TOOL_MAP = {
    "get_executive_summary": get_executive_summary,
    "list_records_requiring_attention": list_records_requiring_attention,
    "compare_provider_health": compare_provider_health,
    "list_unvalidated_assumptions": list_unvalidated_assumptions,
    "run_applied_water_scenario": run_applied_water_scenario,
    "generate_reporting_summary": generate_reporting_summary,
    "generate_exception_report": generate_exception_report,
    "draft_operator_follow_up": draft_operator_follow_up,
}

PRESET_ROUTING: dict[str, str] = {
    "attention": "list_records_requiring_attention",
    "requires_attention": "list_records_requiring_attention",
    "attention_today": "list_records_requiring_attention",
    "provisional": "run_applied_water_scenario",
    "why_provisional": "run_applied_water_scenario",
    "reporting": "generate_reporting_summary",
    "ready_for_reporting": "generate_reporting_summary",
    "pump_without_meter": "generate_exception_report",
    "applied_water_calculation": "run_applied_water_scenario",
    "provider_health": "compare_provider_health",
    "reporting_summary": "generate_reporting_summary",
    "fox_canyon_data": "list_unvalidated_assumptions",
    "assumptions": "list_unvalidated_assumptions",
    "exceptions": "generate_exception_report",
    "follow_up": "draft_operator_follow_up",
}


def _detect_tool(query: str) -> str:
    q = query.lower()
    if any(w in q for w in ("attention", "review", "problem", "issue", "priority")):
        return "list_records_requiring_attention"
    if any(w in q for w in ("summary", "overview", "status")):
        return "get_executive_summary"
    if any(w in q for w in ("provisional", "how calculated", "calculation", "applied water")):
        return "run_applied_water_scenario"
    if any(w in q for w in ("provider", "health", "source", "connected")):
        return "compare_provider_health"
    if any(w in q for w in ("report", "export", "ready")):
        return "generate_reporting_summary"
    if any(w in q for w in ("assumption", "validation", "fox canyon", "what data")):
        return "list_unvalidated_assumptions"
    if any(w in q for w in ("pump", "meter movement")):
        return "generate_exception_report"
    if any(w in q for w in ("follow up", "operator", "action")):
        return "draft_operator_follow_up"
    return "get_executive_summary"


def query_copilot(
    query: str,
    record_id: str | None = None,
    tool_override: str | None = None,
) -> dict[str, Any]:
    """
    Answer a copilot query using deterministic backend tools.

    All answers are grounded in ledger data. The LLM layer (if configured)
    may elaborate the answer but must not add unsupported facts or quantities.
    """
    # Determine tool
    tool_name = tool_override or PRESET_ROUTING.get(query.lower().replace(" ", "_"), None)
    if not tool_name:
        tool_name = _detect_tool(query)

    # Record-specific tools
    if record_id:
        if "ledger" in query.lower():
            result = get_water_ledger(record_id)
        elif "lineage" in query.lower():
            result = show_data_lineage(record_id)
        else:
            result = explain_record(record_id)
    elif tool_name in TOOL_MAP:
        result = TOOL_MAP[tool_name]()
    else:
        result = get_executive_summary()

    # Try optional LLM enhancement
    llm_enhanced = False
    formatted_answer = _format_deterministic_answer(result)

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        try:
            formatted_answer = _llm_format(query, result, api_key)
            llm_enhanced = True
        except Exception as exc:
            logger.warning("LLM enhancement failed, using deterministic fallback: %s", exc)

    return {
        "query": query,
        "tool_used": result.get("tool", tool_name),
        "answer": formatted_answer,
        "structured_result": result,
        "llm_enhanced": llm_enhanced,
        "answer_type": result.get("answer_type", "fact"),
        "calculation_version": CALCULATION_VERSION,
        "disclaimer": (
            "AGRO-AI answers are grounded in deterministic backend tools and source records. "
            "The AI does not approve records, file reports, or claim legal compliance. "
            "All quantities from demonstration scenarios only."
        ),
    }


def _format_deterministic_answer(result: dict[str, Any]) -> str:
    """Format a deterministic tool result into readable text."""
    tool = result.get("tool", "")

    if tool == "get_executive_summary":
        narrative = result.get("narrative", "")
        stats = result.get("stats", {})
        lines = [
            narrative,
            "",
            f"**Records**: {stats.get('total_records', 0)} total | {stats.get('requires_attention', 0)} require attention | {stats.get('ready_for_export', 0)} ready",
            f"**Open exceptions**: {result.get('open_exception_count', 0)}",
            f"**Supported extraction**: {stats.get('supported_extraction_af', 0):.2f} AF (ready records only)",
            "",
            "_All figures from demonstration scenarios. No authorized Fox Canyon data connected._",
        ]
        return "\n".join(lines)

    if tool == "list_records_requiring_attention":
        records = result.get("records", [])
        if not records:
            return "No records currently require attention."
        lines = [f"**{len(records)} record(s) require attention:**", ""]
        for r in records[:8]:
            excs = [e["exception_type"] for e in r.get("open_exceptions", [])]
            lines.append(f"- `{r['record_id']}` | Well: {r['well_id']} | Exceptions: {', '.join(excs) or 'none'}")
        return "\n".join(lines)

    if tool == "compare_provider_health":
        providers = result.get("providers", [])
        lines = ["**Provider Health:**", ""]
        for p in providers:
            icon = "✓" if p["status"] == "connected" else ("✗" if p["status"] == "disabled" else "⚠")
            lines.append(f"- {icon} **{p['label']}**: {p['status']} — {p['message']}")
        return "\n".join(lines)

    if tool == "run_applied_water_scenario":
        return (
            f"**Applied-Water Attribution (DEMO RULESET v0.1 — Provisional)**\n\n"
            f"Total meter records: {result.get('total_meter_records', 0)}\n"
            f"Provisional records: {result.get('provisional_records', 0)}\n"
            f"Interval volume (all meters): {result.get('total_interval_af', 0):.3f} AF\n\n"
            f"_{result.get('disclaimer', '')}_"
        )

    if tool == "generate_reporting_summary":
        return (
            f"**Reporting Summary — {result.get('reporting_period', 'Q1 2026')}**\n\n"
            f"Records: {result.get('total_records', 0)} total | "
            f"{result.get('ready_for_export', 0)} ready | "
            f"{result.get('requires_attention', 0)} requiring attention\n"
            f"Open exceptions: {result.get('open_exceptions', 0)}\n"
            f"Reporting readiness: **{result.get('reporting_readiness', 'Unknown')}**\n\n"
            f"_{result.get('disclaimer', '')}_"
        )

    if tool == "list_unvalidated_assumptions":
        items = result.get("assumptions", [])
        lines = [f"**{len(items)} unvalidated assumption(s):**", ""]
        for a in items:
            lines.append(f"- **{a['category']}**: {a['description']}")
            lines.append(f"  → _To resolve_: {a['what_to_request']}")
        lines.append("")
        lines.append(f"**Recommended next action**: {result.get('recommended_next_action', '')}")
        return "\n".join(lines)

    if tool == "generate_exception_report":
        total = result.get("total_open_exceptions", 0)
        by_type = result.get("by_type", {})
        if not total:
            return "No open exceptions found."
        lines = [f"**{total} open exception(s):**", ""]
        for t, count in by_type.items():
            lines.append(f"- {t.replace('_', ' ')}: {count}")
        return "\n".join(lines)

    if tool == "draft_operator_follow_up":
        items = result.get("follow_up_items", [])
        if not items:
            return "No follow-up items required."
        lines = [f"**{len(items)} follow-up item(s) for operators:**", ""]
        for item in items[:6]:
            lines.append(f"- **{item['well_id']}** — {item['exception_type'].replace('_', ' ')}")
            lines.append(f"  Action: {item['recommended_action'][:120]}...")
        return "\n".join(lines)

    if tool in ("explain_record", "get_water_ledger"):
        r = result.get("record", result)
        return (
            f"**Record {result.get('record_id', r.get('id', '?'))}**\n\n"
            f"Evidence class: {r.get('evidence_class', '?')}\n"
            f"Provider: {r.get('provider', '?')}\n"
            f"Status: {r.get('review_status', '?')}\n"
            f"Interval volume: {r.get('interval_volume', 'N/A')} AF\n"
            f"Attribution: {'provisional' if r.get('attribution_provisional') else 'supported'}\n\n"
            + ("\n".join(f"- {w}" for w in result.get("why_provisional", [])))
        )

    # Generic fallback
    return str(result.get("narrative") or result.get("message") or "Query processed. See structured result for details.")


def _llm_format(query: str, tool_result: dict[str, Any], api_key: str) -> str:
    """Optional LLM formatting layer. Must not add unsupported facts."""
    import anthropic  # type: ignore
    client = anthropic.Anthropic(api_key=api_key)
    deterministic_text = _format_deterministic_answer(tool_result)

    system_prompt = """You are the AGRO-AI Water Intelligence Copilot for Fox Canyon Groundwater Management Agency.

STRICT RULES:
1. You MUST only elaborate on the deterministic tool result provided below.
2. You MUST NOT generate quantities, facts, or conclusions not present in the tool result.
3. You MUST NOT approve records, file reports, or claim legal compliance.
4. You MUST clearly distinguish: FACT, CALCULATION, PROVISIONAL INFERENCE, MISSING INFORMATION, RECOMMENDED ACTION.
5. Cite record IDs, calculation versions, and source hashes when present in the tool result.
6. If information is missing, say so directly.
7. Keep response concise and executive-appropriate."""

    user_prompt = f"""User question: {query}

Deterministic tool result:
{deterministic_text}

Please provide a clear, grounded answer based solely on the tool result above."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text
