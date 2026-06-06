"""Proactive Terris briefing generator for the FCGMA Water Intelligence Copilot.

Produces a 2-3 paragraph natural-language briefing grounded entirely in
deterministic backend data.  If an LLM API key is configured, the structured
narrative is rewritten as analyst prose; otherwise the deterministic text is
returned directly.

LLM configuration (shared with conversation.py):
  TERRIS_LLM_PROVIDER  — "anthropic" (default) | "openai"
  TERRIS_LLM_MODEL     — model name override
  TERRIS_LLM_API_KEY   — provider API key (falls back to ANTHROPIC_API_KEY)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from .gates import compute_all_gates
from .cases import build_cases
from .terris import get_reporting_cycle_status, list_priority_actions
from .ledger import CALCULATION_VERSION

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# LLM config (mirrors conversation.py)
# ─────────────────────────────────────────────

def _get_llm_config() -> tuple[str | None, str, str]:
    """Return (api_key, provider, model). api_key is None when unconfigured."""
    provider = os.getenv("TERRIS_LLM_PROVIDER", "anthropic").lower()
    api_key = (
        os.getenv("TERRIS_LLM_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
    )
    if not api_key or not api_key.strip():
        api_key = None

    default_models = {
        "anthropic": "claude-haiku-4-5-20251001",
        "openai": "gpt-4o-mini",
    }
    model = os.getenv("TERRIS_LLM_MODEL", default_models.get(provider, "claude-haiku-4-5-20251001"))
    return api_key, provider, model


# ─────────────────────────────────────────────
# Narrative builders
# ─────────────────────────────────────────────

def _build_briefing_narrative(
    open_cases: list[dict[str, Any]],
    high_cases: list[dict[str, Any]],
    resolvable: list[dict[str, Any]],
    requires_operator: list[dict[str, Any]],
    requires_agency: list[dict[str, Any]],
    total: int,
    cleared: int,
    under_review_af: float,
    gates: dict[str, Any],
) -> str:
    """Build a 2-3 paragraph natural-language briefing from deterministic parameters.

    The tone is that of a thoughtful senior water-intelligence analyst — direct,
    specific, and action-oriented.  No template fill-in language.
    """
    gate_summary = gates.get("gate_summary", {})
    clear_gates = gate_summary.get("clear", 0)
    total_prerequisite_gates = 4

    # ── Paragraph 1: Reporting position ──────────────────────────────────────
    if total == 0:
        position_sentence = (
            "No records have been loaded into the ledger yet; inject demonstration scenarios "
            "or import AMI CSV data to begin the reporting cycle."
        )
    else:
        pct = round(cleared / total * 100) if total > 0 else 0
        position_sentence = (
            f"The current reporting position for 2026-Q1 is {clear_gates} of "
            f"{total_prerequisite_gates} prerequisite gates clear. "
            f"{cleared} of {total} {'record is' if total == 1 else 'records are'} cleared for reporting "
            f"({pct}%), "
            f"with {under_review_af:.2f} AF currently under provisional review."
        )

    if open_cases:
        case_count = len(open_cases)
        case_word = "case remains" if case_count == 1 else "cases remain"
        case_sentence = f"{case_count} material {case_word} open."
    else:
        case_sentence = "No material cases are currently open."

    paragraph_1 = f"{position_sentence} {case_sentence}"

    # ── Paragraph 2: Most urgent case and resolvability ───────────────────────
    if not open_cases:
        paragraph_2 = (
            "All records are either cleared or pending routine review. "
            "The ledger is clean and no operator or agency action is required at this time."
        )
    else:
        priority_case = high_cases[0] if high_cases else open_cases[0]
        urgency_label = (
            "The highest-priority item"
            if priority_case.get("severity") == "high"
            else "The most pressing open item"
        )
        case_title = priority_case.get("title", "an unresolved case")
        case_af = priority_case.get("affected_quantity_af", 0.0)
        primary_issue = priority_case.get("primary_issue", "requires resolution")
        why = priority_case.get("why_it_matters", "")

        urgency_sentence = (
            f"{urgency_label} is {case_title} ({case_af:.2f} AF affected): {primary_issue}."
        )
        if why and len(why) < 200:
            urgency_sentence += f" {why}"

        # Resolvability breakdown
        resolvability_parts = []
        if resolvable:
            r_word = "case appears" if len(resolvable) == 1 else "cases appear"
            resolvability_parts.append(
                f"{len(resolvable)} {r_word} resolvable with existing evidence"
            )
        if requires_operator:
            op_word = "case requires" if len(requires_operator) == 1 else "cases require"
            resolvability_parts.append(
                f"{len(requires_operator)} {op_word} field operator confirmation"
            )
        if requires_agency:
            ag_word = "case requires" if len(requires_agency) == 1 else "cases require"
            resolvability_parts.append(
                f"{len(requires_agency)} {ag_word} agency notification or CombCode resolution"
            )

        if resolvability_parts:
            resolvability_sentence = "Of the open cases, " + "; ".join(resolvability_parts) + "."
        else:
            resolvability_sentence = ""

        paragraph_2 = " ".join(filter(None, [urgency_sentence, resolvability_sentence]))

    # ── Paragraph 3: Path to close ────────────────────────────────────────────
    gate5_status = gates.get("gates", [{}])[-1].get("status", "not_ready") if gates.get("gates") else "not_ready"

    if gate5_status == "ready_to_close":
        paragraph_3 = (
            "All prerequisite gates are clear. The fastest path to cycle close is a final "
            "review with the Executive Officer, after which the package can be submitted to FCGMA."
        )
    elif resolvable:
        resolvable_af = round(sum(c.get("affected_quantity_af", 0) for c in resolvable), 2)
        paragraph_3 = (
            f"The fastest path to improve readiness is to address the "
            f"{len(resolvable)} {'case' if len(resolvable) == 1 else 'cases'} "
            f"resolvable with existing evidence ({resolvable_af:.2f} AF). "
        )
        if requires_operator:
            paragraph_3 += (
                f"Operator confirmations for {len(requires_operator)} "
                f"{'case' if len(requires_operator) == 1 else 'cases'} should be requested in parallel. "
            )
        if requires_agency:
            paragraph_3 += (
                f"Agency-facing items ({len(requires_agency)} "
                f"{'case' if len(requires_agency) == 1 else 'cases'}) will require FCGMA coordination "
                f"and cannot be resolved unilaterally."
            )
    elif requires_operator:
        paragraph_3 = (
            f"The fastest path forward is to prepare follow-up requests for the field operator covering "
            f"{len(requires_operator)} outstanding {'confirmation' if len(requires_operator) == 1 else 'confirmations'}. "
            "Once operator responses are received, affected records can move to reviewer-approved status."
        )
    elif requires_agency:
        _ag_n = len(requires_agency)
        _ag_verb = "requires" if _ag_n == 1 else "require"
        _ag_word = "case" if _ag_n == 1 else "cases"
        paragraph_3 = (
            f"The remaining {_ag_n} {_ag_word} {_ag_verb} direct FCGMA coordination — "
            "specifically CombCode confirmation or formal agency notification. "
            "Prepare the exception packet now so it is ready when contact is initiated."
        )
    else:
        paragraph_3 = (
            "Generate the reporting package to capture the current ledger state and provide "
            "the Executive Officer with an up-to-date submission-readiness assessment."
        )

    return "\n\n".join(filter(None, [paragraph_1, paragraph_2, paragraph_3]))


# ─────────────────────────────────────────────
# Suggested actions
# ─────────────────────────────────────────────

def _build_suggested_actions(
    open_cases: list[dict[str, Any]],
    resolvable: list[dict[str, Any]],
    requires_operator: list[dict[str, Any]],
    requires_agency: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Return a ranked list of suggested actions the user can take next."""
    actions: list[dict[str, str]] = []

    if open_cases:
        priority_case = open_cases[0]
        actions.append({
            "label": f"Investigate the highest-priority case: {priority_case.get('title', 'open case')}",
            "query": f"Investigate {priority_case.get('title', 'the highest-priority case')}",
            "type": "investigate",
        })

    if requires_operator:
        actions.append({
            "label": f"Prepare evidence requests for the field operator ({len(requires_operator)} "
                     f"{'item' if len(requires_operator) == 1 else 'items'})",
            "query": "Draft operator follow-up requests for open cases requiring field confirmation",
            "type": "request",
        })

    if requires_agency:
        actions.append({
            "label": f"Prepare agency notification items ({len(requires_agency)} "
                     f"{'item' if len(requires_agency) == 1 else 'items'})",
            "query": "Draft FCGMA agency notification items for meter reset and CombCode cases",
            "type": "request",
        })

    actions.append({
        "label": "Simulate fastest path to cycle close",
        "query": "What is the fastest path to close the 2026-Q1 reporting cycle?",
        "type": "simulate",
    })

    actions.append({
        "label": "Generate exception packet",
        "query": "Generate the exception packet for agency notification review",
        "type": "generate",
    })

    actions.append({
        "label": "Generate internal brief for Executive Officer",
        "query": "Generate a reporting-readiness brief for the Executive Officer",
        "type": "generate",
    })

    return actions


# ─────────────────────────────────────────────
# LLM rewrite
# ─────────────────────────────────────────────

def _llm_briefing(
    deterministic_narrative: str,
    cases: list[dict[str, Any]],
    cycle: dict[str, Any],
    api_key: str,
    provider: str,
    model: str,
) -> str:
    """Rewrite the deterministic narrative as natural analyst prose using the LLM.

    Grounding rules:
    - ALL facts must come from the deterministic_narrative provided.
    - Sound like a senior water-intelligence analyst, not a template filler.
    - 2-3 paragraphs maximum.
    - Identify the most urgent item specifically.
    - State clearly what can be resolved with existing evidence.
    - End with a clear recommendation.
    """
    open_count = sum(1 for c in cases if c.get("status") == "open")
    high_count = sum(1 for c in cases if c.get("status") == "open" and c.get("severity") == "high")

    system = (
        "You are Terris, AGRO-AI's Water Intelligence Agent for Fox Canyon Groundwater Management Agency.\n\n"
        "Your task: rewrite the deterministic briefing below as natural analyst prose.\n\n"
        "STRICT RULES:\n"
        "1. Ground ALL facts in the deterministic narrative provided — never invent quantities, "
        "names, or conclusions not present in it.\n"
        "2. Sound like a senior water-intelligence analyst — direct, specific, no filler language.\n"
        "3. 2-3 paragraphs maximum.\n"
        "4. Identify the most urgent item specifically by name if it appears in the input.\n"
        "5. State clearly what can be resolved with existing evidence vs. what requires "
        "operator or agency action.\n"
        "6. End with a clear, single recommendation.\n"
        "7. Do NOT approve records, file regulatory reports, or claim legal compliance.\n"
        "8. Do NOT use phrases like 'Based on the data provided' or 'According to the information'.\n"
        "9. All figures are from illustrative demonstration scenarios — do not imply they are "
        "official Fox Canyon data."
    )

    context_lines = [
        f"Open cases: {open_count}",
        f"High-severity cases: {high_count}",
        f"Reporting cycle status: {cycle.get('status_label', 'unknown')}",
        f"Records ready: {cycle.get('ready_for_export', 0)} of {cycle.get('total_records', 0)}",
    ]
    context_block = "\n".join(context_lines)

    user_content = (
        f"Deterministic briefing to rewrite:\n\n{deterministic_narrative}\n\n"
        f"Supporting context:\n{context_block}\n\n"
        "Please rewrite as natural analyst prose following the rules above."
    )

    if provider == "openai":
        import openai  # type: ignore
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            max_tokens=600,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
        )
        return resp.choices[0].message.content or deterministic_narrative
    else:
        import anthropic  # type: ignore
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=600,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        return resp.content[0].text


# ─────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────

def generate_terris_briefing() -> dict[str, Any]:
    """Generate a proactive Terris briefing from current evidence."""
    gates = compute_all_gates()
    cases = build_cases()
    cycle = get_reporting_cycle_status()
    actions = list_priority_actions()

    open_cases = [c for c in cases if c["status"] == "open"]
    high_cases = [c for c in open_cases if c["severity"] == "high"]

    # Determine what's resolvable with existing evidence
    resolvable: list[dict[str, Any]] = []
    requires_operator: list[dict[str, Any]] = []
    requires_agency: list[dict[str, Any]] = []

    operator_types = {
        "pump_activity_without_meter_movement",
        "backup_estimate_required",
        "missing_telemetry_interval",
    }
    agency_types = {
        "meter_reset_detected",
        "unresolved_combcode",
        "multiplier_change",
    }

    for c in open_cases:
        primary = c["issue_categories"][0] if c["issue_categories"] else ""
        if primary in agency_types:
            requires_agency.append(c)
        elif primary in operator_types:
            requires_operator.append(c)
        else:
            resolvable.append(c)

    # Derive values from cycle status
    total = cycle.get("total_records", 0)
    cleared = cycle.get("ready_for_export", 0)
    under_review_af = cycle.get("provisional_af", 0.0)

    briefing_text = _build_briefing_narrative(
        open_cases, high_cases, resolvable, requires_operator, requires_agency,
        total, cleared, under_review_af, gates,
    )

    # Build LLM-enhanced briefing if configured
    api_key, provider, model = _get_llm_config()
    llm_mode = "structured_safe"

    if api_key:
        try:
            briefing_text = _llm_briefing(briefing_text, cases, cycle, api_key, provider, model)
            llm_mode = "connected_intelligence"
        except Exception as exc:
            logger.warning("Briefing LLM failed, using structured: %s", exc)

    return {
        "briefing": briefing_text,
        "open_case_count": len(open_cases),
        "high_severity_count": len(high_cases),
        "resolvable_count": len(resolvable),
        "requires_operator_count": len(requires_operator),
        "requires_agency_count": len(requires_agency),
        "priority_case": high_cases[0] if high_cases else (open_cases[0] if open_cases else None),
        "quantity_under_review_af": round(under_review_af, 2),
        "suggested_actions": _build_suggested_actions(open_cases, resolvable, requires_operator, requires_agency),
        "llm_mode": llm_mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "calculation_version": CALCULATION_VERSION,
    }
