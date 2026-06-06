"""Conversation engine for Terris — AGRO-AI Water Intelligence Agent.

Manages multi-turn conversation threads with context persistence,
reference resolution, and LLM provider abstraction.

LLM integration:
  TERRIS_LLM_PROVIDER  — "anthropic" (default) | "openai"
  TERRIS_LLM_MODEL     — model name override
  TERRIS_LLM_API_KEY   — provider API key

Modes:
  Connected Intelligence — LLM narrates deterministic tool results
  Structured Safe        — deterministic fallback, no LLM required
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from .terris import (
    run_terris_investigation,
    AGENT_NAME,
    CALCULATION_VERSION,
    _brief_tool_result,
)
from .cases import build_cases
from .ledger import get_record, list_records, ledger_stats

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# In-memory conversation store
# ─────────────────────────────────────────────────────────────────────────────

_CONVERSATIONS: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _thread_id() -> str:
    return f"thread-{uuid.uuid4().hex[:12]}"


# ─────────────────────────────────────────────────────────────────────────────
# Reference resolution
# ─────────────────────────────────────────────────────────────────────────────

_ORDINALS = {
    "first": 0, "1st": 0,
    "second": 1, "2nd": 1,
    "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3,
    "fifth": 4, "5th": 4,
}


def _resolve_references(query: str, ctx: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """Return (resolved_query, record_id, case_id).

    Expands shorthand references like "that well", "the first case", "those records"
    using conversation context from prior turns.
    """
    q = query.lower()
    record_id: str | None = None
    case_id: str | None = None

    # Case ordinal references: "the first case", "case 2", "that case"
    for ordinal, idx in _ORDINALS.items():
        if f"the {ordinal} case" in q or f"{ordinal} case" in q:
            cases = ctx.get("last_cases", [])
            if idx < len(cases):
                case_id = cases[idx]["case_id"]
                query = query + f" [resolved: case={case_id}]"
                break

    if "that case" in q or "this case" in q:
        last = ctx.get("last_case_id")
        if last:
            case_id = last
            query = query + f" [resolved: case={last}]"

    # Well references: "that well", "the well", "FC-WELL-001"
    if "that well" in q or "the well" in q or "this well" in q:
        last_well = ctx.get("last_well_id")
        if last_well:
            query = query.replace("that well", last_well).replace("the well", last_well).replace("this well", last_well)

    # Record references: "that record", "those records", "the record"
    if "that record" in q or "those records" in q or "the record" in q:
        last_recs = ctx.get("last_record_ids", [])
        if last_recs:
            record_id = last_recs[0]
            query = query + f" [resolved: record={record_id}]"

    # Ordinal record references: "the first record", "record 2"
    for ordinal, idx in _ORDINALS.items():
        if f"the {ordinal} record" in q or f"{ordinal} record" in q:
            last_recs = ctx.get("last_record_ids", [])
            if idx < len(last_recs):
                record_id = last_recs[idx]
                query = query + f" [resolved: record={record_id}]"
                break

    return query, record_id, case_id


def _update_context(ctx: dict[str, Any], tool_results: dict[str, Any]) -> None:
    """Update conversation context with references from this turn's tool results."""
    # Cases
    cases = tool_results.get("list_review_cases", [])
    if cases:
        ctx["last_cases"] = cases
        if cases:
            ctx["last_case_id"] = cases[0]["case_id"]

    # Well IDs
    for tool_name, result in tool_results.items():
        if isinstance(result, dict):
            records = result.get("records", result.get("actions", []))
            if isinstance(records, list) and records:
                first = records[0]
                if "well_id" in first:
                    ctx["last_well_id"] = first["well_id"]
                    ctx["last_record_ids"] = [
                        r.get("record_id") or r.get("id", "")
                        for r in records
                        if r.get("record_id") or r.get("id")
                    ][:10]


# ─────────────────────────────────────────────────────────────────────────────
# LLM abstraction
# ─────────────────────────────────────────────────────────────────────────────

def _get_llm_config() -> tuple[str | None, str, str]:
    """Return (api_key, provider, model). api_key is None when unconfigured."""
    provider = os.getenv("TERRIS_LLM_PROVIDER", "anthropic").lower()
    api_key = (
        os.getenv("TERRIS_LLM_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")  # fallback for legacy config
    )
    if not api_key or not api_key.strip():
        api_key = None

    default_models = {
        "anthropic": "claude-haiku-4-5-20251001",
        "openai": "gpt-4o-mini",
    }
    model = os.getenv("TERRIS_LLM_MODEL", default_models.get(provider, "claude-haiku-4-5-20251001"))
    return api_key, provider, model


def _llm_narrate(
    query: str,
    investigation: dict[str, Any],
    conversation_history: list[dict[str, Any]],
    api_key: str,
    provider: str,
    model: str,
) -> str:
    """Call the configured LLM to narrate the deterministic investigation result."""
    det_answer = investigation.get("direct_answer", "")
    evidence_items = [
        f"- {e['tool']}: {e['summary']}"
        for e in investigation.get("evidence_reviewed", [])
    ]
    evidence_text = "\n".join(evidence_items)

    system = (
        "You are Terris, AGRO-AI's Water Intelligence Agent for Fox Canyon Groundwater Management Agency.\n\n"
        "STRICT RULES:\n"
        "1. You MUST only elaborate on the deterministic tool result provided — never invent quantities, "
        "facts, or conclusions not present in the tool result.\n"
        "2. Never approve records, file regulatory reports, or claim legal compliance.\n"
        "3. Distinguish clearly: FACT vs CALCULATION vs PROVISIONAL INFERENCE vs RECOMMENDED ACTION.\n"
        "4. Cite record IDs, calculation versions, and well IDs when they appear in the tool result.\n"
        "5. All figures are from illustrative demonstration scenarios. Never imply they are official data.\n"
        "6. Be conversational, executive-appropriate, and concise. 2-4 sentences unless detail is needed.\n"
        "7. Never show raw tool names (e.g. 'list_priority_actions') — use natural language.\n"
        "8. If the user references prior turns, answer in context of the full conversation thread."
    )

    # Build conversation history for multi-turn context
    messages: list[dict[str, str]] = []
    for turn in conversation_history[-6:]:  # last 6 turns for context
        if turn["role"] in ("user", "assistant"):
            messages.append({"role": turn["role"], "content": turn["content"]})

    # Add current query with tool context
    user_content = (
        f"Question: {query}\n\n"
        f"What the tools found:\n{det_answer}\n\n"
        f"Evidence consulted:\n{evidence_text}\n\n"
        f"Please provide a natural, grounded answer based solely on what the tools found above."
    )
    messages.append({"role": "user", "content": user_content})

    if provider == "openai":
        import openai  # type: ignore
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            max_tokens=500,
            messages=[{"role": "system", "content": system}] + messages,  # type: ignore
        )
        return resp.choices[0].message.content or det_answer
    else:
        import anthropic  # type: ignore
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=500,
            system=system,
            messages=messages,  # type: ignore
        )
        return resp.content[0].text

    return det_answer


def _build_follow_up_suggestions(investigation: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """Return 2-3 contextual follow-up suggestions based on current investigation."""
    intent = investigation.get("intent", "executive_summary")
    tool_results = investigation.get("tool_results", {})

    blocking = 0
    for r in tool_results.values():
        if isinstance(r, dict):
            blocking = max(blocking, r.get("blocking_count", 0))

    suggestions: list[str] = []

    if intent == "review_queue" and blocking > 0:
        suggestions.append("Which well should I investigate first?")
        suggestions.append("Draft the follow-up requests for the operator.")
    elif intent == "reporting_cycle":
        if blocking > 0:
            suggestions.append("Which records are blocking the cycle?")
        suggestions.append("Generate a full reporting-readiness brief.")
    elif intent == "exception_investigation":
        suggestions.append("What follow-up is required for the agency?")
        suggestions.append("Which records require a backup estimate?")
    elif intent == "applied_water":
        suggestions.append("Which records are still provisional?")
        suggestions.append("What does Fox Canyon need to validate this calculation?")
    elif intent == "provider_health":
        suggestions.append("What data would the Ranch Systems adapter add?")
        suggestions.append("Which wells are missing active data feeds?")
    else:
        suggestions.append("What requires my attention today?")
        suggestions.append("Where does the 2026-Q1 cycle stand?")

    suggestions.append("Generate a reporting-readiness brief.")
    return suggestions[:3]


# ─────────────────────────────────────────────────────────────────────────────
# Conversation CRUD
# ─────────────────────────────────────────────────────────────────────────────

def create_conversation(
    title: str | None = None,
    initial_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new conversation thread. Returns the thread metadata."""
    tid = _thread_id()
    now = _now()
    conv = {
        "thread_id": tid,
        "title": title or "Terris — Water Intelligence",
        "created_at": now,
        "updated_at": now,
        "turns": [],
        "context": initial_context or {},
        "message_count": 0,
        "llm_mode": "structured_safe",  # updated on first LLM success
    }
    _CONVERSATIONS[tid] = conv
    return {k: v for k, v in conv.items() if k != "turns"}


def get_conversation(thread_id: str) -> dict[str, Any] | None:
    return _CONVERSATIONS.get(thread_id)


def list_conversations() -> list[dict[str, Any]]:
    return [
        {k: v for k, v in c.items() if k != "turns"}
        for c in sorted(_CONVERSATIONS.values(), key=lambda x: x["updated_at"], reverse=True)
    ]


def add_message(
    thread_id: str,
    user_query: str,
    context_hint: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Add a user message and generate Terris response. Returns the response turn."""
    conv = _CONVERSATIONS.get(thread_id)
    if not conv:
        return None

    ctx = conv["context"]
    history = conv["turns"]

    # Merge any caller-supplied context hints (e.g. "ask about this record")
    if context_hint:
        ctx.update(context_hint)

    # Resolve multi-turn references
    resolved_query, record_id, case_id = _resolve_references(user_query, ctx)

    # Record user turn
    user_turn = {
        "role": "user",
        "content": user_query,
        "timestamp": _now(),
    }
    history.append(user_turn)

    # Run Terris investigation
    investigation = run_terris_investigation(resolved_query, record_id=record_id)

    # Optionally enhance with case context
    if case_id:
        cases = build_cases()
        case = next((c for c in cases if c["case_id"] == case_id), None)
        if case:
            investigation["case_context"] = case

    # Update conversation context from tool results
    _update_context(ctx, investigation.get("tool_results", {}))
    if case_id:
        ctx["last_case_id"] = case_id

    # Try LLM narration
    api_key, provider, model = _get_llm_config()
    llm_mode = "structured_safe"
    narrated_answer = investigation.get("direct_answer", "")

    if api_key:
        try:
            narrated_answer = _llm_narrate(
                user_query,
                investigation,
                history,
                api_key, provider, model,
            )
            llm_mode = "connected_intelligence"
        except Exception as exc:
            logger.warning("Terris LLM narration failed, using structured safe mode: %s", exc)

    conv["llm_mode"] = llm_mode

    # Build evidence trail (collapsed by default)
    evidence_trail = [
        {
            "tool": e["tool"],
            "summary": e["summary"],
        }
        for e in investigation.get("evidence_reviewed", [])
    ]

    # Contextual follow-ups
    follow_ups = _build_follow_up_suggestions(investigation, ctx)

    # Build assistant turn
    assistant_turn = {
        "role": "assistant",
        "content": narrated_answer,
        "timestamp": _now(),
        "evidence_trail": evidence_trail,
        "recommended_action": investigation.get("recommended_action"),
        "follow_up_suggestions": follow_ups,
        "llm_mode": llm_mode,
        "investigation_meta": {
            "intent": investigation.get("intent"),
            "answer_type": investigation.get("answer_type"),
            "calculation_version": CALCULATION_VERSION,
        },
    }
    history.append(assistant_turn)

    conv["message_count"] = len([t for t in history if t["role"] == "user"])
    conv["updated_at"] = _now()

    return assistant_turn


def get_history(thread_id: str) -> list[dict[str, Any]]:
    conv = _CONVERSATIONS.get(thread_id)
    if not conv:
        return []
    return list(conv["turns"])
