"""Conversation engine for Terris — AGRO-AI Water Intelligence Agent.

Manages multi-turn conversation threads with context persistence,
reference resolution, and LLM provider abstraction.

LLM integration:
  TERRIS_LLM_PROVIDER  — "anthropic" (default) | "openai"
  TERRIS_LLM_MODEL     — model name override
  TERRIS_LLM_API_KEY   — provider API key (falls back to ANTHROPIC_API_KEY)

Modes:
  Connected Intelligence — LLM narrates deterministic tool results
  Structured Safe        — deterministic fallback, no LLM required
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from .terris import (
    run_terris_investigation,
    AGENT_NAME,
    CALCULATION_VERSION,
    _brief_tool_result,
    _n,
)
from .cases import build_cases
from .ledger import get_record, list_records, ledger_stats

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# In-memory stores
# ─────────────────────────────────────────────────────────────────────────────

_CONVERSATIONS: dict[str, dict[str, Any]] = {}
_JOBS: dict[str, dict[str, Any]] = {}  # active streaming jobs
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="terris-")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _thread_id() -> str:
    return f"thread-{uuid.uuid4().hex[:12]}"


def _job_id() -> str:
    return f"job-{uuid.uuid4().hex[:12]}"


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

    Expands natural references like "that well", "the first case", "those records"
    using conversation context from prior turns.
    """
    q = query.lower()
    record_id: str | None = None
    case_id: str | None = None

    # Case ordinal references: "the first case", "case 2", "that issue"
    for ordinal, idx in _ORDINALS.items():
        if f"the {ordinal} case" in q or f"{ordinal} case" in q or f"the {ordinal} issue" in q:
            cases = ctx.get("last_cases", [])
            if idx < len(cases):
                case_id = cases[idx]["case_id"]
                query = query + f" [resolved: case={case_id}]"
                break

    if "that case" in q or "this case" in q or "that issue" in q or "the issue" in q:
        last = ctx.get("last_case_id")
        if last and "[resolved:" not in query:
            case_id = last
            query = query + f" [resolved: case={last}]"

    # Well references: "that well", "the well", "this well", "that meter"
    for phrase in ("that well", "the well", "this well", "that meter"):
        if phrase in q:
            last_well = ctx.get("last_well_id")
            if last_well:
                query = query.replace(phrase, last_well)
            break

    # Record references: "that record", "those records", "the record", "the affected quantity"
    if any(ph in q for ph in ("that record", "those records", "the record", "the affected")):
        last_recs = ctx.get("last_record_ids", [])
        if last_recs:
            record_id = last_recs[0]
            if "[resolved:" not in query:
                query = query + f" [resolved: record={record_id}]"

    # Ordinal record references: "the first record"
    for ordinal, idx in _ORDINALS.items():
        if f"the {ordinal} record" in q or f"{ordinal} record" in q:
            last_recs = ctx.get("last_record_ids", [])
            if idx < len(last_recs):
                record_id = last_recs[idx]
                if "[resolved:" not in query:
                    query = query + f" [resolved: record={record_id}]"
                break

    return query, record_id, case_id


def _update_context(ctx: dict[str, Any], tool_results: dict[str, Any]) -> None:
    """Update conversation context with references from this turn's tool results."""
    # Cases — update last_cases and last_case_id
    actions = tool_results.get("list_priority_actions", {})
    if actions:
        action_list = actions.get("actions", [])
        # Build case-like objects from actions for reference resolution
        ctx["last_action_wells"] = [a["well_id"] for a in action_list[:5]]

    blocking = tool_results.get("list_records_blocking_reporting", {})
    if blocking:
        records_list = blocking.get("records", [])
        if records_list:
            ctx["last_well_id"] = records_list[0]["well_id"]
            ctx["last_record_ids"] = [r["record_id"] for r in records_list[:10]]

    # Update well from explain_record
    rec_result = tool_results.get("explain_record", {})
    if rec_result.get("record_id"):
        ctx["last_record_ids"] = [rec_result["record_id"]]


def _update_context_from_cases(ctx: dict[str, Any], cases: list[dict]) -> None:
    if cases:
        ctx["last_cases"] = cases
        ctx["last_case_id"] = cases[0]["case_id"]
        ctx["last_well_id"] = cases[0]["well_id"]


# ─────────────────────────────────────────────────────────────────────────────
# LLM abstraction
# ─────────────────────────────────────────────────────────────────────────────

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
        "anthropic": "claude-sonnet-4-6",
        "openai": "gpt-4o",
    }
    model = os.getenv("TERRIS_LLM_MODEL", default_models.get(provider, "claude-sonnet-4-6"))
    return api_key, provider, model


_TERRIS_SYSTEM = """\
You are Terris, AGRO-AI's Water Intelligence Agent for Fox Canyon Groundwater Management Agency (FCGMA).

IDENTITY:
You are a senior water-intelligence analyst. You think clearly, communicate directly, and provide operational value to groundwater managers and district executives.

BEHAVIORAL RULES:
1. Answer based ONLY on the deterministic tool results provided. Never invent quantities, facts, or conclusions not present in the tool result.
2. Sound like a thoughtful analyst — vary your structure based on the question. Do not force every answer into the same template.
3. For executive/summary questions: lead with a clear conclusion, then ranked priorities, then what to do next.
4. For calculation questions: plain-English explanation first, then compact table if helpful, then assumptions and lineage.
5. For simple factual questions: one direct sentence, one evidence reference, one relevant action.
6. For report/draft requests: produce the document directly in clean professional format, then note what's still unresolved.
7. For multi-turn follow-ups: answer naturally in context of the full conversation — don't re-introduce context the user already has.
8. NEVER use "(s)" pluralization — write "1 record", "2 records", "1 case", "4 cases".
9. NEVER expose raw tool names (e.g. list_priority_actions) in the answer.
10. NEVER claim legal compliance, approve records, or state that records are ready for regulatory submission.
11. Distinguish clearly when something is a FACT, a CALCULATION, PROVISIONAL, or a RECOMMENDATION.
12. State uncertainty directly. Don't fabricate confidence.
13. All figures are from illustrative demonstration scenarios. Never imply they are official Fox Canyon data.
14. When drafting a document (evidence request, memo, brief), produce it fully — don't hedge with "here is a draft."

WATER-ACCOUNTING DOMAIN:
- Fox Canyon GMA regulates groundwater extraction in Ventura County, CA
- Reporting period: 2026-Q1, submission deadline: 2026-04-30
- CombCode = FCGMA combination code linking a well to its management zone
- The applied-water model uses DEMO RULESET v0.1, not validated by Fox Canyon
- Backup estimates require pre-approval from FCGMA
- Meter changes require agency notification
- Ranch Systems adapter is intentionally disabled — no Ranch Systems data is available

RESPONSE LENGTH:
- Simple questions: 1-3 sentences
- Complex analysis: up to 4 paragraphs
- Drafted documents: as long as needed, properly formatted
- Never pad with disclaimers or generic recommendations already in the evidence trail
"""


def _format_tool_context(investigation: dict[str, Any]) -> str:
    """Build a concise tool-result summary for the LLM prompt."""
    lines = [f"Question: {investigation.get('query', '')}"]
    lines.append("")
    lines.append("What the tools found:")
    lines.append(investigation.get("direct_answer", ""))
    lines.append("")

    tool_results = investigation.get("tool_results", {})
    if tool_results:
        lines.append("Evidence details:")
        for tool_name, result in tool_results.items():
            brief = _brief_tool_result(tool_name, result)
            lines.append(f"  • {brief}")

    # Add case context if available
    case_ctx = investigation.get("case_context")
    if case_ctx:
        lines.append("")
        lines.append(f"Case context: {case_ctx.get('title', '')} — {case_ctx.get('primary_issue', '')}")
        lines.append(f"  Why it matters: {case_ctx.get('why_it_matters', '')[:200]}")
        lines.append(f"  Required evidence: {'; '.join(case_ctx.get('required_evidence', [])[:3])}")

    lines.append("")
    lines.append("Recommended action (deterministic):")
    lines.append(investigation.get("recommended_action", ""))

    return "\n".join(lines)


def _llm_narrate(
    query: str,
    investigation: dict[str, Any],
    conversation_history: list[dict[str, Any]],
    api_key: str,
    provider: str,
    model: str,
) -> str:
    """Call the configured LLM to narrate the deterministic investigation result."""
    tool_context = _format_tool_context(investigation)

    messages: list[dict[str, str]] = []
    # Include last 6 turns for multi-turn context
    for turn in conversation_history[-6:]:
        if turn["role"] in ("user", "assistant"):
            messages.append({"role": turn["role"], "content": turn["content"]})

    messages.append({
        "role": "user",
        "content": (
            f"{tool_context}\n\n"
            "Provide a natural, grounded answer based solely on the tool findings above. "
            "Adapt your structure to the question. Do not repeat the recommended action "
            "verbatim — incorporate it naturally if relevant."
        ),
    })

    try:
        if provider == "openai":
            import openai  # type: ignore
            client = openai.OpenAI(api_key=api_key)
            resp = client.chat.completions.create(
                model=model,
                max_tokens=700,
                messages=[{"role": "system", "content": _TERRIS_SYSTEM}] + messages,  # type: ignore
            )
            return resp.choices[0].message.content or investigation.get("direct_answer", "")
        else:
            import anthropic  # type: ignore
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=model,
                max_tokens=700,
                system=_TERRIS_SYSTEM,
                messages=messages,  # type: ignore
            )
            return resp.content[0].text
    except Exception:
        raise


def _build_follow_up_suggestions(investigation: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """Return 2-3 contextual follow-up suggestions based on current investigation."""
    intent = investigation.get("intent", "executive_summary")
    tool_results = investigation.get("tool_results", {})
    cases = ctx.get("last_cases", [])
    last_case = ctx.get("last_case_id")

    suggestions: list[str] = []

    # Case-specific follow-ups
    if last_case and intent in ("review_queue", "exception_investigation"):
        suggestions.append("What evidence are we missing for this case?")
        suggestions.append("Can we resolve it with what we already have?")
        suggestions.append("Draft the request we should send to the operator.")
        return suggestions[:3]

    # Cycle status follow-ups
    if intent == "reporting_cycle":
        blocking = tool_results.get("list_records_blocking_reporting", {}).get("blocking_count", 0)
        if blocking:
            suggestions.append("Which case should I focus on first?")
            suggestions.append("What happens to the reporting position if we clear the top case?")
        suggestions.append("Generate an internal brief for the Executive Officer.")
        return suggestions[:3]

    # Priority/attention follow-ups
    if intent == "review_queue":
        suggestions.append("Why is the first one the most urgent?")
        suggestions.append("Which cases can be resolved using evidence we already have?")
        suggestions.append("What should we request from the operator?")
        return suggestions[:3]

    # Provider health follow-ups
    if intent == "provider_health":
        suggestions.append("Which wells are missing active data feeds?")
        suggestions.append("What data would Fox Canyon need to validate our calculations?")
        return suggestions[:2]

    # Applied water follow-ups
    if intent == "applied_water":
        suggestions.append("Which records are still provisional?")
        suggestions.append("What does Fox Canyon need to validate this calculation?")
        return suggestions[:2]

    # Default executive-level suggestions
    suggestions.append("What would you focus on first?")
    suggestions.append("Which cases can be resolved using evidence we already have?")
    suggestions.append("Generate an exception packet for agency review.")
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
        "llm_mode": "structured_safe",
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
    on_progress: Callable[[dict], None] | None = None,
) -> dict[str, Any] | None:
    """Add a user message and generate Terris response. Returns the response turn.

    on_progress: optional callback called with {"stage", "label", "status"} events
    as the investigation proceeds.
    """
    conv = _CONVERSATIONS.get(thread_id)
    if not conv:
        return None

    ctx = conv["context"]
    history = conv["turns"]

    # Merge caller-supplied context hints
    if context_hint:
        ctx.update(context_hint)

    # Resolve multi-turn references
    resolved_query, record_id, case_id = _resolve_references(user_query, ctx)

    # Record user turn
    user_turn = {"role": "user", "content": user_query, "timestamp": _now()}
    history.append(user_turn)

    # Run Terris investigation (with progress callback)
    investigation = run_terris_investigation(
        resolved_query,
        record_id=record_id,
        on_progress=on_progress,
    )

    # Optionally enrich with case context
    if case_id:
        cases = build_cases()
        case = next((c for c in cases if c["case_id"] == case_id), None)
        if case:
            investigation["case_context"] = case

    # Update conversation context
    _update_context(ctx, investigation.get("tool_results", {}))
    if case_id:
        ctx["last_case_id"] = case_id

    # Build cases for reference resolution on follow-ups
    try:
        current_cases = build_cases()
        _update_context_from_cases(ctx, current_cases)
    except Exception:
        pass

    # Try LLM narration
    api_key, provider, model = _get_llm_config()
    llm_mode = "structured_safe"
    narrated_answer = investigation.get("direct_answer", "")

    if api_key:
        if on_progress:
            on_progress({"stage": "llm_synthesis", "label": "Synthesizing findings…", "status": "started"})
        try:
            narrated_answer = _llm_narrate(
                user_query, investigation, history, api_key, provider, model,
            )
            llm_mode = "connected_intelligence"
            if on_progress:
                on_progress({"stage": "llm_synthesis", "label": "Synthesizing findings…", "status": "completed"})
        except Exception as exc:
            logger.warning("Terris LLM narration failed, using structured safe mode: %s", exc)

    conv["llm_mode"] = llm_mode

    # Build evidence trail
    evidence_trail = [
        {
            "tool": e["tool"],
            "summary": e["summary"],
            "user_label": e.get("user_label", e["tool"].replace("_", " ").title()),
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
        "progress_labels": investigation.get("progress_labels", []),
        "reviewed_summary": investigation.get("reviewed_summary", ""),
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


# ─────────────────────────────────────────────────────────────────────────────
# Streaming job support
# ─────────────────────────────────────────────────────────────────────────────

def start_message_job(
    thread_id: str,
    user_query: str,
    context_hint: dict[str, Any] | None = None,
) -> str | None:
    """Start an async investigation job. Returns job_id. Events available via poll_job_events()."""
    conv = _CONVERSATIONS.get(thread_id)
    if not conv:
        return None

    jid = _job_id()
    _JOBS[jid] = {
        "job_id": jid,
        "thread_id": thread_id,
        "status": "running",
        "events": [],
        "result": None,
        "error": None,
    }

    def _run():
        job = _JOBS[jid]

        def on_event(evt: dict) -> None:
            job["events"].append(evt)

        try:
            result = add_message(thread_id, user_query, context_hint, on_progress=on_event)
            job["result"] = result
            job["status"] = "complete"
        except Exception as exc:
            job["error"] = str(exc)
            job["status"] = "error"
        finally:
            job["events"].append({"stage": "__done__", "label": "", "status": "done"})

    _executor.submit(_run)
    return jid


def poll_job(job_id: str, since_index: int = 0) -> dict[str, Any] | None:
    """Poll job state. Returns events[since_index:], status, and result when done."""
    job = _JOBS.get(job_id)
    if not job:
        return None
    return {
        "job_id": job_id,
        "status": job["status"],
        "events": job["events"][since_index:],
        "result": job["result"] if job["status"] == "complete" else None,
        "error": job.get("error"),
    }
