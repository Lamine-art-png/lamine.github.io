"""Conversation engine for Terris — AGRO-AI Water Intelligence Agent.

Manages multi-turn conversation threads with context persistence,
reference resolution, and LLM provider abstraction.

LLM integration:
  TERRIS_LLM_PROVIDER         — "gemini_demo" | "ollama" | "anthropic" | "openai" (default: anthropic)
  TERRIS_LLM_MODEL            — model name override for paid providers
  TERRIS_LLM_API_KEY          — provider API key for paid providers
  TERRIS_GEMINI_API_KEY       — Gemini API key (free developer tier)
  TERRIS_GEMINI_MODEL         — Gemini model (default: gemini-3.5-flash)
  TERRIS_EXTERNAL_DEMO_ONLY   — restrict external model to illustrative data (default: true)
  TERRIS_EXTERNAL_BLOCK_PRIVATE — block private/confidential provenance (default: true)
  TERRIS_EXTERNAL_ALLOWED_PROVENANCE — comma-separated allowed provenance categories
  TERRIS_EXTERNAL_MAX_TOOL_ITERATIONS — max tool iterations for Gemini (default: 6)
  TERRIS_EXTERNAL_TIMEOUT_SECONDS     — wall-clock timeout for Gemini (default: 120)
  TERRIS_OLLAMA_BASE_URL      — Ollama base URL (default: http://127.0.0.1:11434)
  TERRIS_OLLAMA_MODEL         — Ollama model (default: llama3.1:8b)
  TERRIS_OLLAMA_NUM_CTX       — context window (default: 32768)
  TERRIS_OLLAMA_MAX_TOOL_ITERATIONS — max agent iterations for Ollama (default: 6)
  TERRIS_OLLAMA_TIMEOUT_SECONDS     — wall-clock timeout (default: 180)

Provider priority (gemini_demo illustrative demo):
  1. gemini_demo_intelligence — Gemini free tier, demo-only safety gate active
  2. structured_safe          — deterministic fallback

All preserved providers:
  local_intelligence     — Ollama running, model installed, tool-calling works
  local_degraded         — Ollama unreachable or model missing
  gemini_demo_intelligence — Gemini configured, safety gate active, working
  gemini_demo_degraded   — Gemini configured but failing (rate limit, auth, etc.)
  connected_intelligence — paid LLM active and working
  connected_degraded     — paid LLM configured but failing
  structured_safe        — deterministic fallback only

Demo-only safety gate (TERRIS_EXTERNAL_BLOCK_PRIVATE=true):
  Allowed provenance: public_context, sanitized_replay, injected_demo_scenario
  Blocked provenance: authorized_live_private, confidential_customer, credential, unknown
  Any blocked provenance causes external call refusal and structured_safe fallback.
  A discreet explanation is included in the Runtime intelligence section.
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
    STAGE_PROGRESS_LABELS,
    _brief_tool_result,
    _n,
)
from .cases import build_cases
from .ledger import get_record, list_records, ledger_stats

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# In-memory stores
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Provenance safety constants (demo-only external model gate)
# ─────────────────────────────────────────────────────────────────────────────

_BLOCKED_PROVENANCE_CATEGORIES: frozenset[str] = frozenset({
    "authorized_live_private",
    "confidential_customer",
    "credential",
    "unknown",
})
_ALLOWED_PROVENANCE_CATEGORIES: frozenset[str] = frozenset({
    "public_context",
    "sanitized_replay",
    "injected_demo_scenario",
})

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
# LLM abstraction + provider health model
# ─────────────────────────────────────────────────────────────────────────────

# Persisted health state for the running process
_PROVIDER_HEALTH: dict[str, Any] = {
    "mode": "structured_safe",
    "sdk_available": False,
    "last_check_at": None,
    "last_error_redacted": None,
    "process_start": datetime.now(timezone.utc).isoformat(),
}

_DEEP_INTENT_KEYWORDS = frozenset({
    "reconciliation", "executive", "board", "trace", "source-to-report",
    "lineage", "walk me through", "explain", "deep", "brief", "full",
    "everything", "comprehensive", "summary", "investigate", "analysis",
    "position", "cycle stand", "going on", "happening",
})
_SIMPLE_INTENT_KEYWORDS = frozenset({
    "how many", "count", "total", "what is", "define", "who", "when",
    "list", "show", "status of",
})


def _choose_reasoning_effort(query: str, intent: str, base_effort: str) -> str:
    """Adapt reasoning effort based on query depth.

    base_effort (from env) is the ceiling; we may reduce it for simpler queries.
    """
    q = query.lower()
    if intent in ("executive_summary", "reporting_cycle", "applied_water", "data_gap"):
        return base_effort  # always use configured ceiling for these
    deep_hit = any(kw in q for kw in _DEEP_INTENT_KEYWORDS)
    simple_hit = any(kw in q for kw in _SIMPLE_INTENT_KEYWORDS) and not deep_hit
    if deep_hit:
        return base_effort
    if simple_hit:
        return "medium" if base_effort == "xhigh" else base_effort
    return "high" if base_effort == "xhigh" else base_effort


def _get_llm_config() -> tuple[str | None, str, str, str]:
    """Return (api_key, provider, model, reasoning_effort). api_key is None for Ollama/unconfigured."""
    provider = os.getenv("TERRIS_LLM_PROVIDER", "anthropic").lower()

    if provider == "ollama":
        # Ollama never requires a cloud key
        api_key = None
        model = os.getenv("TERRIS_OLLAMA_MODEL", "llama3.1:8b")
        reasoning_effort = "local"
        return api_key, provider, model, reasoning_effort

    if provider == "gemini_demo":
        # Gemini free developer tier — illustrative/sanitized data only
        api_key = os.getenv("TERRIS_GEMINI_API_KEY")
        if not api_key or not api_key.strip():
            api_key = None
        model = os.getenv("TERRIS_GEMINI_MODEL", "gemini-3.5-flash")
        reasoning_effort = "medium"
        return api_key, provider, model, reasoning_effort

    api_key = (
        os.getenv("TERRIS_LLM_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
    )
    if not api_key or not api_key.strip():
        api_key = None

    default_models = {
        "anthropic": "claude-sonnet-4-6",
        "openai": "gpt-5.5",
    }
    model = os.getenv("TERRIS_LLM_MODEL", default_models.get(provider, "claude-sonnet-4-6"))
    reasoning_effort = os.getenv("TERRIS_LLM_REASONING_EFFORT", "xhigh")
    return api_key, provider, model, reasoning_effort


def _get_ollama_config() -> dict[str, Any]:
    """Return Ollama-specific configuration."""
    return {
        "base_url": os.getenv("TERRIS_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        "model": os.getenv("TERRIS_OLLAMA_MODEL", "llama3.1:8b"),
        "fallback_model": os.getenv("TERRIS_OLLAMA_FALLBACK_MODEL", "llama3.2:3b"),
        "num_ctx": int(os.getenv("TERRIS_OLLAMA_NUM_CTX", "32768")),
        "max_tool_iterations": int(os.getenv("TERRIS_OLLAMA_MAX_TOOL_ITERATIONS", "6")),
        "timeout_seconds": float(os.getenv("TERRIS_OLLAMA_TIMEOUT_SECONDS", "180")),
        "stream": os.getenv("TERRIS_OLLAMA_STREAM", "true").lower() == "true",
    }


def _get_gemini_config() -> dict[str, Any]:
    """Return Gemini Demo Intelligence configuration."""
    return {
        "model": os.getenv("TERRIS_GEMINI_MODEL", "gemini-3.5-flash"),
        "max_tool_iterations": int(os.getenv("TERRIS_EXTERNAL_MAX_TOOL_ITERATIONS", "6")),
        "timeout_seconds": float(os.getenv("TERRIS_EXTERNAL_TIMEOUT_SECONDS", "120")),
        "demo_only": os.getenv("TERRIS_EXTERNAL_DEMO_ONLY", "true").lower() == "true",
        "block_private": os.getenv("TERRIS_EXTERNAL_BLOCK_PRIVATE", "true").lower() == "true",
        "allowed_provenance": set(
            os.getenv(
                "TERRIS_EXTERNAL_ALLOWED_PROVENANCE",
                "public_context,sanitized_replay,injected_demo_scenario",
            ).split(",")
        ),
    }


def _check_ollama_reachable(base_url: str | None = None) -> bool:
    """Return True if Ollama responds on the expected base URL."""
    import urllib.request
    import urllib.error
    url = base_url or os.getenv("TERRIS_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=4) as resp:  # noqa: S310
            return resp.status == 200
    except Exception:
        return False


def _check_ollama_loopback_only(base_url: str | None = None) -> bool:
    """Return True when Ollama base_url is loopback (127.0.0.1 or localhost)."""
    url = base_url or os.getenv("TERRIS_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    return "127.0.0.1" in url or "localhost" in url


def _check_ollama_model_available(model: str, base_url: str | None = None) -> bool:
    """Return True if the model is installed in the local Ollama instance."""
    import json
    import urllib.request
    import urllib.error
    url = base_url or os.getenv("TERRIS_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=4) as resp:  # noqa: S310
            data = json.loads(resp.read())
            installed = [m.get("name", "") for m in data.get("models", [])]
            # Accept partial match: "llama3.1:8b" in "llama3.1:8b-instruct-q4..."
            return any(model.split(":")[0] in n for n in installed) or model in installed
    except Exception:
        return False


def _check_sdk_available(provider: str) -> bool:
    """Return True if the provider SDK can be imported."""
    try:
        if provider == "openai":
            import openai  # noqa: F401
        elif provider == "ollama":
            return True  # Ollama uses stdlib urllib — no external SDK required
        elif provider == "gemini_demo":
            from google import genai  # noqa: F401
        else:
            import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def get_provider_health() -> dict[str, Any]:
    """Return safe provider health diagnostics (never exposes key value)."""
    api_key, provider, model, reasoning_effort = _get_llm_config()
    sdk_ok = _check_sdk_available(provider)

    if provider == "ollama":
        cfg = _get_ollama_config()
        base_url = cfg["base_url"]
        reachable = _check_ollama_reachable(base_url)
        loopback = _check_ollama_loopback_only(base_url)
        model_ok = _check_ollama_model_available(model, base_url) if reachable else False

        stored_mode = _PROVIDER_HEALTH.get("mode", "structured_safe")
        if stored_mode in ("local_intelligence", "local_degraded"):
            mode = stored_mode
        elif reachable and model_ok and loopback:
            mode = "local_intelligence"
        elif reachable and not model_ok:
            mode = "local_degraded"
        elif not reachable:
            mode = "local_degraded"
        else:
            mode = "local_degraded"

        return {
            "mode": mode,
            "llm_mode": mode,
            "provider": "ollama",
            "model": model,
            "reasoning_effort": "local",
            "key_configured": False,
            "cloud_key_required": False,
            "cloud_inference_disabled": True,
            "sdk_available": True,
            "ollama_reachable": reachable,
            "ollama_loopback_only": loopback,
            "model_installed": model_ok,
            "base_url_safe": base_url if loopback else "WARN: not loopback",
            "last_check_at": _PROVIDER_HEALTH.get("last_check_at"),
            "last_error_redacted": _PROVIDER_HEALTH.get("last_error_redacted"),
            "process_start": _PROVIDER_HEALTH.get("process_start"),
            "note": (
                "Local Intelligence Mode. No cloud key required. "
                "All inference runs on-device via Ollama. "
                "Configure with: bash scripts/configure_terris_local.sh"
                + ("" if loopback else
                   " WARNING: Ollama not bound to loopback. See Part 2 of setup guide.")
                + ("" if model_ok else
                   f" Model '{model}' not installed. Run: ollama pull {model}")
            ),
        }

    if provider == "gemini_demo":
        cfg = _get_gemini_config()
        sdk_ok = _check_sdk_available("gemini_demo")
        key_set = bool(api_key)
        demo_only = cfg["demo_only"]
        block_private = cfg["block_private"]
        active_health = _get_gemini_active_health()

        stored_mode = _PROVIDER_HEALTH.get("mode", "structured_safe")
        if stored_mode in ("gemini_demo_intelligence", "gemini_demo_degraded"):
            mode = stored_mode
        elif key_set and sdk_ok and demo_only:
            mode = "gemini_demo_intelligence"
        elif key_set and not sdk_ok:
            mode = "gemini_demo_degraded"
        elif key_set:
            mode = "gemini_demo_intelligence"
        else:
            mode = "structured_safe"

        return {
            "mode": mode,
            "llm_mode": mode,
            "provider": "gemini_demo",
            "model": model,
            "reasoning_effort": "medium",
            "key_configured": key_set,
            "sdk_available": sdk_ok,
            "demo_only_safety_active": demo_only,
            "blocked_private_provenance": block_private,
            "allowed_provenance": os.getenv(
                "TERRIS_EXTERNAL_ALLOWED_PROVENANCE",
                "public_context,sanitized_replay,injected_demo_scenario",
            ),
            "cloud_key_required": True,
            "cloud_inference_disabled": False,
            "schema_valid": active_health["schema_valid"],
            "recent_provider_health": active_health["recent_health"],
            "health_check_age_seconds": active_health["health_check_age_seconds"],
            "health_ttl_seconds": active_health["health_ttl_seconds"],
            "rate_limited": active_health["rate_limited"],
            "rate_limited_at": active_health["rate_limited_at"],
            "fallback_active": active_health["fallback_active"],
            "last_check_at": _PROVIDER_HEALTH.get("last_check_at"),
            "last_error_redacted": _PROVIDER_HEALTH.get("last_error_redacted"),
            "process_start": _PROVIDER_HEALTH.get("process_start"),
            "note": (
                "Gemini Demo Intelligence. Illustrative and sanitized records only. "
                "Private data is blocked before any external model call. "
                "Configure with: bash scripts/configure_terris_gemini_demo.sh. "
                "API rate limits: see aistudio.google.com/usage"
            ),
        }

    # Paid providers (anthropic, openai)
    if not api_key:
        mode = "structured_safe"
    elif not sdk_ok:
        mode = "connected_degraded"
    else:
        mode = _PROVIDER_HEALTH.get("mode", "structured_safe")

    return {
        "mode": mode,
        "llm_mode": mode,
        "provider": provider,
        "model": model if model else f"(default for {provider})",
        "reasoning_effort": reasoning_effort,
        "key_configured": bool(api_key),
        "cloud_key_required": True,
        "cloud_inference_disabled": False,
        "sdk_available": sdk_ok,
        "last_check_at": _PROVIDER_HEALTH.get("last_check_at"),
        "last_error_redacted": _PROVIDER_HEALTH.get("last_error_redacted"),
        "process_start": _PROVIDER_HEALTH.get("process_start"),
        "note": (
            "Key value is never returned. "
            "Mode 'connected_degraded' means configuration exists but the provider "
            "call failed — check sdk_available and last_error_redacted. "
            "Mode 'restart_required' means .env.local is configured but the process "
            "was started before the file existed."
        ),
    }


def _record_provider_success(local: bool = False, gemini: bool = False) -> None:
    if local:
        _PROVIDER_HEALTH["mode"] = "local_intelligence"
    elif gemini:
        _PROVIDER_HEALTH["mode"] = "gemini_demo_intelligence"
    else:
        _PROVIDER_HEALTH["mode"] = "connected_intelligence"
    _PROVIDER_HEALTH["last_check_at"] = datetime.now(timezone.utc).isoformat()
    _PROVIDER_HEALTH["last_error_redacted"] = None
    _PROVIDER_HEALTH["sdk_available"] = True


def _record_provider_failure(exc: Exception, local: bool = False, gemini: bool = False) -> None:
    import re as _re
    raw = type(exc).__name__ + ": " + str(exc)[:120]
    # Scrub any sk-... / sk-ant-... or AIza... key-like tokens before storing
    redacted = _re.sub(r"sk-[A-Za-z0-9\-]{8,}", "[REDACTED]", raw)
    redacted = _re.sub(r"AIza[A-Za-z0-9\-_]{8,}", "[REDACTED]", redacted)[:100]
    if local:
        _PROVIDER_HEALTH["mode"] = "local_degraded"
    elif gemini:
        _PROVIDER_HEALTH["mode"] = "gemini_demo_degraded"
    else:
        _PROVIDER_HEALTH["mode"] = "connected_degraded"
    _PROVIDER_HEALTH["last_check_at"] = datetime.now(timezone.utc).isoformat()
    _PROVIDER_HEALTH["last_error_redacted"] = redacted


# ─────────────────────────────────────────────────────────────────────────────
# Provenance safety gate (demo-only external model protection)
# ─────────────────────────────────────────────────────────────────────────────

def _validate_evidence_provenance(evidence_items: list[dict[str, Any]]) -> tuple[bool, str]:
    """Return (safe, reason). Blocks forbidden provenance categories from reaching external models."""
    cfg = _get_gemini_config()
    if not cfg["block_private"]:
        return True, ""
    for item in evidence_items:
        prov = item.get("provenance", "unknown")
        if prov in _BLOCKED_PROVENANCE_CATEGORIES:
            return False, f"Blocked provenance category: {prov}"
    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# Per-tool external provenance policy registry
# Each tool must explicitly declare its external access policy.
# Unknown tools → FAIL CLOSED (external_allowed=False).
# ─────────────────────────────────────────────────────────────────────────────

_DEMO_TOOL_POLICY: dict[str, Any] = {
    "external_allowed": True,
    "allowed_output_provenance": frozenset({
        "public_context", "sanitized_replay", "injected_demo_scenario"
    }),
    "sends_summary_only": True,
    "blocks_unknown_fields": True,
    "requires_anonymization": False,
    "safe_for_gemini_demo": True,
    "field_redaction_policy": "summary_only",
}

TOOL_EXTERNAL_PROVENANCE_POLICY: dict[str, dict[str, Any]] = {
    "get_reporting_cycle_status":       {**_DEMO_TOOL_POLICY, "audit_category": "cycle_status"},
    "list_priority_actions":            {**_DEMO_TOOL_POLICY, "audit_category": "priority_queue"},
    "list_records_blocking_reporting":  {**_DEMO_TOOL_POLICY, "audit_category": "blocking_records"},
    "get_gate_status":                  {**_DEMO_TOOL_POLICY, "audit_category": "gate_status"},
    "get_high_severity_cases":          {**_DEMO_TOOL_POLICY, "audit_category": "case_severity"},
    "get_applied_water_summary":        {**_DEMO_TOOL_POLICY, "audit_category": "applied_water"},
    "get_exception_count_by_type":      {**_DEMO_TOOL_POLICY, "audit_category": "exception_types"},
    "list_wells_with_issues":           {**_DEMO_TOOL_POLICY, "audit_category": "well_status"},
    "get_operator_action_items":        {**_DEMO_TOOL_POLICY, "audit_category": "operator_actions"},
    "get_agency_action_items":          {**_DEMO_TOOL_POLICY, "audit_category": "agency_actions"},
    "get_combcode_status":              {**_DEMO_TOOL_POLICY, "audit_category": "combcode_status"},
    "get_cycle_readiness":              {**_DEMO_TOOL_POLICY, "audit_category": "cycle_readiness"},
    "get_reconciliation_status":        {**_DEMO_TOOL_POLICY, "audit_category": "reconciliation"},
    "generate_reporting_brief":         {**_DEMO_TOOL_POLICY, "audit_category": "reporting_brief"},
    "generate_exception_packet":        {**_DEMO_TOOL_POLICY, "audit_category": "exception_packet"},
    "draft_follow_up_request":          {**_DEMO_TOOL_POLICY, "audit_category": "follow_up_request"},
    "draft_evidence_request":           {**_DEMO_TOOL_POLICY, "audit_category": "evidence_request"},
    "compare_provider_health":          {**_DEMO_TOOL_POLICY, "audit_category": "provider_health"},
    "list_unvalidated_assumptions":     {**_DEMO_TOOL_POLICY, "audit_category": "assumptions"},
    "run_applied_water_scenario":       {**_DEMO_TOOL_POLICY, "audit_category": "water_scenario"},
}

# Default for any tool NOT in the registry: FAIL CLOSED
_TOOL_POLICY_DEFAULT: dict[str, Any] = {
    "external_allowed": False,
    "allowed_output_provenance": frozenset(),
    "sends_summary_only": False,
    "blocks_unknown_fields": True,
    "requires_anonymization": True,
    "safe_for_gemini_demo": False,
    "field_redaction_policy": "block",
    "audit_category": "unknown",
}


def _get_tool_policy(tool_name: str) -> dict[str, Any]:
    """Return the external provenance policy for a tool. Unknown tools fail closed."""
    return TOOL_EXTERNAL_PROVENANCE_POLICY.get(tool_name, _TOOL_POLICY_DEFAULT)


def _get_tool_provenance(tool_name: str) -> str:
    """Return a representative provenance tag for a tool, derived from its registry policy."""
    policy = _get_tool_policy(tool_name)
    allowed = policy.get("allowed_output_provenance", frozenset())
    if not allowed:
        return "unknown"
    # Prefer injected_demo_scenario for demo tools, otherwise first allowed
    if "injected_demo_scenario" in allowed:
        return "injected_demo_scenario"
    return next(iter(allowed))


def _sanitize_evidence_for_external(tool_results: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a minimized, provenance-tagged evidence list safe for external models.

    Uses the per-tool registry to determine provenance. Tools not in the registry
    are excluded (fail closed). Strips unnecessary fields, sends summaries only.
    """
    items: list[dict[str, Any]] = []
    for tool_name, result in tool_results.items():
        policy = _get_tool_policy(tool_name)
        if not policy["external_allowed"]:
            continue  # fail closed — do not include in external payload
        brief = _brief_tool_result(tool_name, result)
        prov = _get_tool_provenance(tool_name)
        items.append({
            "tool": tool_name,
            "brief": brief,
            "provenance": prov,
        })
    return items


# ─────────────────────────────────────────────────────────────────────────────
# Operational query classification
# ─────────────────────────────────────────────────────────────────────────────

_GENERAL_CONVERSATIONAL_PATTERNS: frozenset[str] = frozenset({
    "what can you", "what can terris", "who are you", "what are you",
    "help me with", "explain the portal", "what is terris", "how does terris",
    "what is agro", "tell me about terris", "what is this portal",
    "introduce yourself", "what do you do",
})

_OPERATIONAL_INDICATORS: frozenset[str] = frozenset({
    "cycle", "reporting", "position", "attention", "provisional",
    "applied water", "extraction", "wells", "records", "cases",
    "evidence", "brief", "exception", "gate", "status", "readiness",
    "quarantined", "missing", "unresolved", "prioritize", "priority",
    "resolve", "review", "fc-well", "snapshot", "reconciliation",
    "submission", "deadline", "acreage", " af ", "acre", "permit",
    "measurement", "meter", "pump", "combcode", "parcel", "lineage",
    "source", "provider", "wiseconn", "ami", "cimis", "ranch systems",
    "going on", "stand", "what requires", "what should", "which records",
    "which wells", "draft", "generate brief", "explain fc-", "trace",
    "walk me through", "how did", "how does the", "what is the current",
    "what are the", "show me the", "are we ready", "can we",
})


def _classify_query_operational(query: str) -> bool:
    """Return True if the query requires water-intelligence operational tool calling.

    General conversational questions (identity, portal explanation) do not require
    tools. All water-intelligence operational questions require deterministic tool
    calling before any answer synthesis.
    """
    q = query.lower().strip()
    # Short general queries
    if any(p in q for p in _GENERAL_CONVERSATIONAL_PATTERNS):
        return False
    # Any operational indicator makes it operational
    if any(kw in q for kw in _OPERATIONAL_INDICATORS):
        return True
    # Queries < 3 words are probably short factual — require tools conservatively
    words = q.split()
    if len(words) < 3:
        return False
    # Default: treat as operational to ensure deterministic grounding
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Evidence map and quantity validation
# ─────────────────────────────────────────────────────────────────────────────

import re as _re_module

_WATER_QTY_PATTERN = _re_module.compile(
    r'(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:af\b|acre-?feet|acre feet)',
    _re_module.IGNORECASE,
)


def _build_evidence_map(tool_raw_results: dict[str, Any]) -> dict[str, Any]:
    """Extract all numeric quantities from deterministic tool results."""
    evidence: dict[str, Any] = {}

    def _extract(obj: Any, prefix: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    evidence[key] = float(v)
                elif isinstance(v, str) and v:
                    evidence[key] = v
                elif isinstance(v, (dict, list)):
                    _extract(v, key)
        elif isinstance(obj, list):
            for i, item in enumerate(obj[:30]):
                _extract(item, f"{prefix}[{i}]")

    for tool_name, result in tool_raw_results.items():
        if isinstance(result, dict):
            _extract(result, tool_name)

    return evidence


def _validate_answer_quantities(
    answer: str,
    evidence_map: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Validate water quantities (af/acre-feet) in the answer against approved evidence.

    Only validates significant water quantities; does not block general counts or
    percentages. Returns (valid, issues).
    """
    if not answer or not evidence_map:
        return True, []

    matches = _WATER_QTY_PATTERN.findall(answer)
    if not matches:
        return True, []

    # Build approved numeric values from evidence (with tolerance)
    approved_values: set[float] = set()
    for v in evidence_map.values():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            fv = float(v)
            if fv > 0:
                approved_values.add(fv)

    if not approved_values:
        return True, []

    issues: list[str] = []
    for match_str in matches:
        clean = match_str.replace(",", "")
        try:
            val = float(clean)
        except ValueError:
            continue
        if val <= 0:
            continue

        found = any(
            abs(val - av) <= max(0.05 * av, 0.5)
            for av in approved_values
        )
        if not found:
            issues.append(f"Water quantity '{match_str} af' not found in deterministic evidence")

    return len(issues) == 0, issues


# ─────────────────────────────────────────────────────────────────────────────
# Gemini schema validation and active health TTL
# ─────────────────────────────────────────────────────────────────────────────

_GEMINI_SCHEMA_VALID: bool | None = None


def _get_gemini_schema_valid() -> bool:
    """Validate Gemini tool schemas once at first call. Returns False → degrade safely."""
    global _GEMINI_SCHEMA_VALID
    if _GEMINI_SCHEMA_VALID is not None:
        return _GEMINI_SCHEMA_VALID
    try:
        tools = _build_gemini_tool_list()
        if not tools:
            _GEMINI_SCHEMA_VALID = False
            return False
        try:
            from google.genai import types as _gt  # type: ignore
            total_decls = sum(
                len(getattr(t, "function_declarations", []))
                for t in tools
            )
            _GEMINI_SCHEMA_VALID = total_decls == len(_AGENT_TOOL_SCHEMAS)
        except Exception:
            _GEMINI_SCHEMA_VALID = len(tools) > 0
    except Exception:
        _GEMINI_SCHEMA_VALID = False
    return _GEMINI_SCHEMA_VALID or False


def _get_gemini_active_health() -> dict[str, Any]:
    """Return active Gemini health based on schema validity and last-call TTL.

    Does NOT make external API calls; uses the cached state from the last
    successful or failed call and applies the configured TTL.
    """
    ttl = float(os.getenv("TERRIS_GEMINI_HEALTH_TTL_SECONDS", "120"))
    schema_valid = _get_gemini_schema_valid()

    last_check = _PROVIDER_HEALTH.get("last_check_at")
    health_age: float = -1.0
    health_fresh = False
    if last_check:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_check)).total_seconds()
            health_age = round(age, 1)
            health_fresh = age < ttl
        except Exception:
            pass

    stored_mode = _PROVIDER_HEALTH.get("mode", "structured_safe")
    if health_fresh and stored_mode == "gemini_demo_intelligence":
        recent_health = "healthy"
    elif health_fresh and stored_mode == "gemini_demo_degraded":
        recent_health = "degraded"
    else:
        recent_health = "unknown"  # TTL expired — do not misrepresent as healthy

    rate_limited = _PROVIDER_HEALTH.get("rate_limited", False)
    rate_limited_at = _PROVIDER_HEALTH.get("rate_limited_at")

    return {
        "schema_valid": schema_valid,
        "recent_health": recent_health,
        "health_check_age_seconds": health_age,
        "health_ttl_seconds": ttl,
        "rate_limited": rate_limited,
        "rate_limited_at": rate_limited_at,
        "fallback_active": not (schema_valid and recent_health == "healthy"),
        "note": (
            "Actual API rate limits vary by model and project. "
            "Check current limits at aistudio.google.com/usage"
        ),
    }


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
    reasoning_effort: str = "xhigh",
) -> str:
    """Call the configured LLM to narrate the deterministic investigation result."""
    tool_context = _format_tool_context(investigation)

    messages: list[dict[str, str]] = []
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
                max_tokens=1200,
                messages=[{"role": "system", "content": _TERRIS_SYSTEM}] + messages,  # type: ignore
            )
            return resp.choices[0].message.content or investigation.get("direct_answer", "")
        else:
            import anthropic  # type: ignore
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=model,
                max_tokens=1200,
                system=_TERRIS_SYSTEM,
                messages=messages,  # type: ignore
            )
            return resp.content[0].text
    except Exception:
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Bounded LLM tool-using agent loop (Part 6)
# ─────────────────────────────────────────────────────────────────────────────

_AGENT_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {"name": "get_reporting_cycle_status", "description": "Get current cycle readiness, blocking exception count, and submission deadline."},
    {"name": "list_priority_actions", "description": "Get ranked action queue — top cases requiring attention."},
    {"name": "list_records_blocking_reporting", "description": "List records with open exceptions that block cycle close."},
    {"name": "get_gate_status", "description": "Get all five reporting gate statuses and overall summary position."},
    {"name": "get_high_severity_cases", "description": "Get open cases with high severity and total affected AF."},
    {"name": "get_applied_water_summary", "description": "Get provisional applied-water attribution summary."},
    {"name": "get_exception_count_by_type", "description": "Get breakdown of open exceptions by type and severity."},
    {"name": "list_wells_with_issues", "description": "List wells that have at least one open exception."},
    {"name": "get_operator_action_items", "description": "Get cases requiring field operator confirmation."},
    {"name": "get_agency_action_items", "description": "Get cases requiring FCGMA agency notification."},
    {"name": "get_combcode_status", "description": "Get CombCode and parcel mapping completion status."},
    {"name": "get_cycle_readiness", "description": "Get detailed cycle readiness: self-service vs operator vs agency items."},
    {"name": "get_reconciliation_status", "description": "Get latest reconciliation snapshot summary."},
    {"name": "generate_reporting_brief", "description": "Generate an executive reporting-readiness brief."},
    {"name": "generate_exception_packet", "description": "Compile exception packet for agency notification review."},
    {"name": "draft_follow_up_request", "description": "Draft follow-up requests for operator or agency action."},
    {"name": "draft_evidence_request", "description": "Draft structured evidence requests for wells with open issues."},
    {"name": "compare_provider_health", "description": "Compare provider feed health and connectivity status."},
    {"name": "list_unvalidated_assumptions", "description": "List model assumptions requiring Fox Canyon validation."},
    {"name": "run_applied_water_scenario", "description": "Run and explain the applied-water attribution scenario."},
]

_MAX_AGENT_ITERATIONS = int(os.getenv("TERRIS_MAX_AGENT_ITERATIONS", "6"))


def _build_anthropic_tool_list() -> list[dict[str, Any]]:
    """Convert tool schemas to Anthropic tool-use format."""
    tools = []
    for t in _AGENT_TOOL_SCHEMAS:
        tools.append({
            "name": t["name"],
            "description": t["description"],
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        })
    return tools


def _build_openai_tool_list() -> list[dict[str, Any]]:
    """Convert tool schemas to OpenAI function/tool format."""
    tools = []
    for t in _AGENT_TOOL_SCHEMAS:
        tools.append({
            "type": "function",
            "name": t["name"],
            "description": t["description"],
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        })
    return tools


def _build_ollama_tool_list() -> list[dict[str, Any]]:
    """Convert tool schemas to Ollama/OpenAI-compatible tool format for local models."""
    tools = []
    for t in _AGENT_TOOL_SCHEMAS:
        tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        })
    return tools


def _build_gemini_tool_list() -> list[Any]:
    """Convert tool schemas to Gemini FunctionDeclaration format (google-genai SDK)."""
    try:
        from google.genai import types  # type: ignore

        declarations = []
        for t in _AGENT_TOOL_SCHEMAS:
            declarations.append(
                types.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters={"type": "OBJECT", "properties": {}},
                )
            )
        return [types.Tool(function_declarations=declarations)]
    except Exception:
        return []


def _run_ollama_agent_loop(
    user_query: str,
    conversation_history: list[dict[str, Any]],
    model: str,
    on_progress: Callable[[dict], None] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Bounded tool-using agent loop using Ollama local chat API.

    Uses the Ollama /api/chat endpoint with tool_choice and tool schemas.
    Returns (final_answer, audit_log). No cloud key required.

    Falls back gracefully if the model does not support tool calling.
    """
    import json
    import time
    import urllib.request
    import urllib.error
    from .terris import TERRIS_TOOL_MAP

    cfg = _get_ollama_config()
    base_url = cfg["base_url"]
    max_iters = cfg["max_tool_iterations"]
    timeout = cfg["timeout_seconds"]
    num_ctx = cfg["num_ctx"]
    fallback_model = cfg["fallback_model"]
    tools = _build_ollama_tool_list()
    audit_log: list[dict[str, Any]] = []
    start_time = time.monotonic()

    # Build message history (last 8 turns for context window efficiency)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _TERRIS_SYSTEM},
    ]
    for turn in conversation_history[-8:]:
        if turn["role"] in ("user", "assistant"):
            messages.append({"role": turn["role"], "content": turn.get("content", "")})
    messages.append({"role": "user", "content": user_query})

    def _post_chat(msgs: list[dict], use_tools: bool = True) -> dict:
        payload: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "stream": False,
            "options": {"num_ctx": num_ctx},
        }
        if use_tools:
            payload["tools"] = tools
        data = json.dumps(payload).encode()
        req = urllib.request.Request(  # noqa: S310
            f"{base_url}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read())

    for iteration in range(max_iters):
        if time.monotonic() - start_time > timeout:
            break

        try:
            response = _post_chat(messages, use_tools=True)
        except Exception as exc:
            _record_provider_failure(exc, local=True)
            # Try without tools as degraded fallback
            try:
                response = _post_chat(messages, use_tools=False)
                text = (response.get("message") or {}).get("content", "")
                if text:
                    _record_provider_success(local=True)
                    return text, audit_log
            except Exception as exc2:
                _record_provider_failure(exc2, local=True)
                raise
            raise

        msg = response.get("message") or {}
        tool_calls = msg.get("tool_calls") or []
        content = msg.get("content") or ""

        if not tool_calls:
            # No tool calls — model produced final answer
            if content:
                _record_provider_success(local=True)
                return content, audit_log
            # Empty content with no tools — synthesize from investigation
            break

        # Execute each tool call
        tool_result_messages: list[dict[str, Any]] = []
        # Append the assistant message with tool_calls
        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

        for tc in tool_calls:
            fn_info = tc.get("function") or {}
            tool_name = fn_info.get("name", "")
            fn = TERRIS_TOOL_MAP.get(tool_name)
            label = STAGE_PROGRESS_LABELS.get(
                f"invoke_{tool_name}",
                _get_tool_progress_label(tool_name),
            )

            if on_progress:
                on_progress({"stage": f"agent_invoke_{tool_name}", "label": label, "status": "started"})

            try:
                result = fn() if fn else {"error": f"Tool not available: {tool_name}"}
                brief = _brief_tool_result(tool_name, result)
                audit_log.append({
                    "iteration": iteration + 1,
                    "tool": tool_name,
                    "status": "completed",
                    "brief": brief,
                })
                tool_result_messages.append({
                    "role": "tool",
                    "content": brief,
                })
                if on_progress:
                    on_progress({"stage": f"agent_invoke_{tool_name}", "label": label, "status": "completed"})
            except Exception as exc:
                audit_log.append({
                    "iteration": iteration + 1,
                    "tool": tool_name,
                    "status": "error",
                    "error": str(exc)[:120],
                })
                tool_result_messages.append({
                    "role": "tool",
                    "content": f"Error executing {tool_name}: {str(exc)[:80]}",
                })
                if on_progress:
                    on_progress({"stage": f"agent_invoke_{tool_name}", "label": label, "status": "error"})

        messages.extend(tool_result_messages)

    # Max iterations or timeout reached — do a final synthesis pass without tools
    if audit_log:
        if on_progress:
            on_progress({"stage": "llm_synthesis", "label": "Preparing a recommendation…", "status": "started"})
        try:
            # Condense tool results into a synthesis prompt
            tool_summary = "\n".join(
                f"• {e['tool']}: {e.get('brief', e.get('error', ''))}"
                for e in audit_log if e["status"] == "completed"
            )
            synthesis_messages = [
                {"role": "system", "content": _TERRIS_SYSTEM},
                *[m for m in messages if m["role"] in ("user", "assistant") and m.get("content")],
                {
                    "role": "user",
                    "content": (
                        f"Based on the following tool findings, answer: {user_query}\n\n"
                        f"Tool findings:\n{tool_summary}\n\n"
                        "Provide a natural, grounded analytical answer. Do not expose tool names."
                    ),
                },
            ]
            response = _post_chat(synthesis_messages, use_tools=False)
            text = (response.get("message") or {}).get("content", "")
            if text:
                _record_provider_success(local=True)
                return text, audit_log
        except Exception as exc:
            _record_provider_failure(exc, local=True)

    _record_provider_failure(RuntimeError("max iterations reached without final answer"), local=True)
    return "", audit_log


def _get_tool_progress_label(tool_name: str) -> str:
    """Map tool name to a natural, high-level progress label (no internal function names)."""
    labels = {
        "get_reporting_cycle_status": "Reviewing the reporting-cycle status…",
        "list_priority_actions": "Analysing the reporting-cycle blockers…",
        "list_records_blocking_reporting": "Tracing affected meter records…",
        "get_gate_status": "Evaluating reporting-cycle gates…",
        "get_high_severity_cases": "Reviewing high-severity cases…",
        "get_applied_water_summary": "Evaluating the applied-water position…",
        "get_exception_count_by_type": "Reviewing exceptions by type…",
        "list_wells_with_issues": "Checking wells with open issues…",
        "get_operator_action_items": "Checking operator action items…",
        "get_agency_action_items": "Reviewing agency notifications required…",
        "get_combcode_status": "Reviewing CombCode and parcel relationships…",
        "get_cycle_readiness": "Analysing cycle-close readiness…",
        "get_reconciliation_status": "Reviewing the latest reconciliation snapshot…",
        "generate_reporting_brief": "Preparing reporting-readiness brief…",
        "generate_exception_packet": "Compiling exception packet…",
        "draft_follow_up_request": "Drafting follow-up request…",
        "draft_evidence_request": "Drafting evidence request…",
        "compare_provider_health": "Comparing provider evidence…",
        "list_unvalidated_assumptions": "Reviewing governance assumptions…",
        "run_applied_water_scenario": "Evaluating applied-water attribution scenario…",
    }
    return labels.get(tool_name, f"Reviewing {tool_name.replace('_', ' ')}…")


def _run_gemini_agent_loop(
    user_query: str,
    conversation_history: list[dict[str, Any]],
    api_key: str,
    model: str,
    on_progress: Callable[[dict], None] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Bounded tool-using agent loop using Google Gemini (google-genai SDK).

    Hardened: mandatory tool calling for operational queries (mode=ANY), per-tool
    policy check (fail-closed for unknown tools), quantity-level answer validation,
    and TTL-based health. Returns (final_answer, audit_log).

    Falls back to structured_safe if:
    - Schema validation fails at entry
    - The SDK is not installed
    - The API key is invalid
    - Blocked provenance is detected
    - Rate limits are exceeded (429)
    - Operational question receives no tool calls after one retry
    - Any unrecoverable error occurs
    """
    import time
    from .terris import TERRIS_TOOL_MAP

    # Schema validation guard — fail closed before any API call
    if not _get_gemini_schema_valid():
        logger.warning("Terris Gemini: schema validation failed — falling back to structured_safe")
        _record_provider_failure(RuntimeError("schema_invalid"), gemini=True)
        return "", []

    cfg = _get_gemini_config()
    max_iters = cfg["max_tool_iterations"]
    timeout = cfg["timeout_seconds"]
    audit_log: list[dict[str, Any]] = []
    tool_raw_results: dict[str, Any] = {}
    start_time = time.monotonic()

    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except ImportError as exc:
        _record_provider_failure(exc, gemini=True)
        return "", audit_log

    try:
        client = genai.Client(api_key=api_key)
    except Exception as exc:
        _record_provider_failure(exc, gemini=True)
        return "", audit_log

    # Classify query: operational queries require mandatory deterministic tool calling
    is_operational = _classify_query_operational(user_query)

    # Build conversation contents (last 8 turns)
    contents: list[Any] = []
    for turn in conversation_history[-8:]:
        role = "user" if turn["role"] == "user" else "model"
        text = turn.get("content", "")
        if text and isinstance(text, str):
            try:
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text)]))
            except Exception:
                contents.append({"role": role, "parts": [{"text": text}]})
    try:
        contents.append(types.Content(role="user", parts=[types.Part.from_text(user_query)]))
    except Exception:
        contents.append({"role": "user", "parts": [{"text": user_query}]})

    tools = _build_gemini_tool_list()
    tool_names = [t["name"] for t in _AGENT_TOOL_SCHEMAS]

    def _make_config(force_tools: bool = False) -> Any:
        try:
            if force_tools and tools:
                tool_cfg = types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="ANY",
                        allowed_function_names=tool_names,
                    )
                )
                return types.GenerateContentConfig(
                    system_instruction=_TERRIS_SYSTEM,
                    tools=tools,
                    tool_config=tool_cfg,
                    temperature=0.3,
                    max_output_tokens=1500,
                )
            elif tools:
                return types.GenerateContentConfig(
                    system_instruction=_TERRIS_SYSTEM,
                    tools=tools,
                    temperature=0.3,
                    max_output_tokens=1500,
                )
            else:
                return types.GenerateContentConfig(
                    system_instruction=_TERRIS_SYSTEM,
                    temperature=0.3,
                    max_output_tokens=1500,
                )
        except Exception:
            return None

    def _call_gemini(use_tools: bool = True, force_tool_mode: bool = False) -> Any:
        cfg_obj = _make_config(force_tools=force_tool_mode and use_tools)
        kwargs: dict[str, Any] = {"model": model, "contents": contents}
        if cfg_obj is not None:
            if not use_tools:
                try:
                    kwargs["config"] = types.GenerateContentConfig(
                        system_instruction=_TERRIS_SYSTEM,
                        temperature=0.3,
                        max_output_tokens=1500,
                    )
                except Exception:
                    kwargs["config"] = cfg_obj
            else:
                kwargs["config"] = cfg_obj
        return client.models.generate_content(**kwargs)

    _retried_for_tools = False

    for iteration in range(max_iters):
        if time.monotonic() - start_time > timeout:
            logger.warning("Terris Gemini agent loop hit timeout after %d iterations", iteration)
            break

        # First call for operational queries uses forced tool mode (mode=ANY)
        force_mode = is_operational and iteration == 0 and not _retried_for_tools

        try:
            response = _call_gemini(use_tools=bool(tools), force_tool_mode=force_mode)
        except Exception as exc:
            err_str = str(exc)
            if "429" in err_str or "quota" in err_str.lower() or "resource_exhausted" in err_str.lower():
                logger.warning("Terris Gemini rate limit reached: %s", exc)
                _PROVIDER_HEALTH["rate_limited"] = True
                _PROVIDER_HEALTH["rate_limited_at"] = datetime.now(timezone.utc).isoformat()
                _record_provider_failure(exc, gemini=True)
                return "", audit_log
            _record_provider_failure(exc, gemini=True)
            logger.warning("Terris Gemini call failed: %s", exc)
            return "", audit_log

        # Extract function calls from response
        try:
            candidate = response.candidates[0]
            parts = list(candidate.content.parts)
        except Exception:
            try:
                text = response.text
                if text:
                    _record_provider_success(gemini=True)
                    return text, audit_log
            except Exception:
                pass
            break

        fn_calls = []
        text_parts = []
        for part in parts:
            fn_call = getattr(part, "function_call", None)
            if fn_call and getattr(fn_call, "name", None):
                fn_calls.append((part, fn_call))
            else:
                txt = getattr(part, "text", None)
                if txt:
                    text_parts.append(txt)

        if not fn_calls:
            # Mandatory tool enforcement for operational queries
            if is_operational and not _retried_for_tools and not audit_log:
                _retried_for_tools = True
                logger.info("Terris Gemini: no tools on operational query — retrying with forced tool mode")
                try:
                    contents.append(
                        types.Content(
                            role="user",
                            parts=[types.Part.from_text(
                                "Please use the available tools to retrieve the current "
                                "water-intelligence data before answering. Do not answer from memory."
                            )],
                        )
                    )
                except Exception:
                    contents.append({"role": "user", "parts": [{"text": "Use the available tools to retrieve current water-intelligence data before answering."}]})
                continue  # retry

            if is_operational and not audit_log:
                # Still no tools after retry — fall back
                logger.warning("Terris Gemini: no tools called after retry for operational query — falling back")
                _record_provider_failure(RuntimeError("no_tools_called_on_operational_query"), gemini=True)
                return "", audit_log

            # Non-operational or tools already called — accept answer
            final_text = "".join(text_parts).strip()
            if not final_text:
                try:
                    final_text = response.text or ""
                except Exception:
                    pass

            if final_text:
                if tool_raw_results:
                    evidence_map = _build_evidence_map(tool_raw_results)
                    valid, issues = _validate_answer_quantities(final_text, evidence_map)
                    if not valid:
                        for issue in issues:
                            logger.warning("Terris Gemini quantity mismatch: %s", issue)
                        audit_log.append({
                            "iteration": iteration + 1,
                            "tool": "_quantity_validation",
                            "status": "warning",
                            "issues": issues,
                        })
                _record_provider_success(gemini=True)
                return final_text, audit_log
            break

        # Append model's turn with function calls
        try:
            contents.append(candidate.content)
        except Exception:
            pass

        # Execute each tool call
        fn_response_parts: list[Any] = []
        for _part, fn_call in fn_calls:
            tool_name = fn_call.name
            policy = _get_tool_policy(tool_name)

            # Per-tool policy check — fail closed for unknown/unregistered tools
            if not policy["external_allowed"]:
                logger.warning("Terris Gemini: tool %r not in provenance registry — blocked (fail closed)", tool_name)
                audit_log.append({
                    "iteration": iteration + 1,
                    "tool": tool_name,
                    "status": "blocked",
                    "reason": "not_in_provenance_registry",
                })
                try:
                    fn_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": "Tool not available in this context."},
                        )
                    )
                except Exception:
                    pass
                continue

            fn = TERRIS_TOOL_MAP.get(tool_name)
            label = _get_tool_progress_label(tool_name)

            if on_progress:
                on_progress({"stage": f"agent_invoke_{tool_name}", "label": label, "status": "started"})

            try:
                result = fn() if fn else {"error": f"Tool not available: {tool_name}"}
                tool_raw_results[tool_name] = result  # accumulate for evidence map
                brief = _brief_tool_result(tool_name, result)

                # Provenance safety check before including in context
                evidence_item = {
                    "tool": tool_name,
                    "brief": brief,
                    "provenance": _get_tool_provenance(tool_name),
                }
                safe, reason = _validate_evidence_provenance([evidence_item])
                if not safe:
                    logger.warning("Provenance safety gate blocked tool result: %s — %s", tool_name, reason)
                    audit_log.append({
                        "iteration": iteration + 1,
                        "tool": tool_name,
                        "status": "blocked",
                        "reason": reason,
                    })
                    brief = "Result blocked by provenance safety gate — private data remained local."
                else:
                    audit_log.append({
                        "iteration": iteration + 1,
                        "tool": tool_name,
                        "status": "completed",
                        "brief": brief,
                    })

                try:
                    fn_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": brief},
                        )
                    )
                except Exception:
                    fn_response_parts.append({"function_response": {"name": tool_name, "response": {"result": brief}}})

                if on_progress:
                    on_progress({"stage": f"agent_invoke_{tool_name}", "label": label, "status": "completed"})

            except Exception as exc:
                audit_log.append({
                    "iteration": iteration + 1,
                    "tool": tool_name,
                    "status": "error",
                    "error": str(exc)[:120],
                })
                try:
                    fn_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"error": f"Tool error: {str(exc)[:80]}"},
                        )
                    )
                except Exception:
                    pass
                if on_progress:
                    on_progress({"stage": f"agent_invoke_{tool_name}", "label": label, "status": "error"})

        # Append tool results as user turn
        if fn_response_parts:
            try:
                contents.append(types.Content(role="user", parts=fn_response_parts))
            except Exception:
                pass

    # Max iterations or timeout — synthesis pass without tools
    if audit_log:
        if on_progress:
            on_progress({"stage": "llm_synthesis", "label": "Preparing a recommendation…", "status": "started"})
        try:
            tool_summary = "\n".join(
                f"• {e['tool']}: {e.get('brief', e.get('error', ''))}"
                for e in audit_log
                if e["status"] == "completed"
            )
            synthesis_query = (
                f"Based on the following tool findings, answer: {user_query}\n\n"
                f"Tool findings:\n{tool_summary}\n\n"
                "Provide a natural, grounded analytical answer. Do not expose tool names."
            )
            try:
                synth_contents = [
                    *[c for c in contents if isinstance(c, dict) or getattr(c, "role", None) == "user"],
                    types.Content(role="user", parts=[types.Part.from_text(synthesis_query)]),
                ]
            except Exception:
                synth_contents = [{"role": "user", "parts": [{"text": synthesis_query}]}]

            synth_response = client.models.generate_content(
                model=model,
                contents=synth_contents,
                config=types.GenerateContentConfig(
                    system_instruction=_TERRIS_SYSTEM,
                    temperature=0.3,
                    max_output_tokens=1500,
                ),
            )
            try:
                text = synth_response.text or ""
            except Exception:
                text = ""
            if not text:
                try:
                    text = "".join(
                        getattr(p, "text", "") or ""
                        for p in synth_response.candidates[0].content.parts
                    )
                except Exception:
                    pass
            if text:
                if tool_raw_results:
                    evidence_map = _build_evidence_map(tool_raw_results)
                    valid, issues = _validate_answer_quantities(text, evidence_map)
                    if not valid:
                        for issue in issues:
                            logger.warning("Terris Gemini synthesis quantity mismatch: %s", issue)
                        audit_log.append({
                            "iteration": -1,
                            "tool": "_synthesis_quantity_validation",
                            "status": "warning",
                            "issues": issues,
                        })
                _record_provider_success(gemini=True)
                return text, audit_log
        except Exception as exc:
            _record_provider_failure(exc, gemini=True)

    _record_provider_failure(RuntimeError("max iterations reached without answer"), gemini=True)
    return "", audit_log


def _run_openai_agent_loop(
    user_query: str,
    conversation_history: list[dict[str, Any]],
    api_key: str,
    model: str,
    reasoning_effort: str,
    on_progress: Callable[[dict], None] | None = None,
    previous_response_id: str | None = None,
) -> tuple[str, list[dict[str, Any]], str | None]:
    """
    Bounded tool-using agent loop using the OpenAI Responses API (openai >= 1.54).

    Returns (final_answer, audit_log, last_response_id).
    last_response_id should be persisted in the conversation for follow-up context.
    """
    import json
    import time
    from .terris import TERRIS_TOOL_MAP

    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        _record_provider_failure(ImportError("openai not installed"))
        return ("OpenAI library not installed. Run: pip install openai>=1.54.0", [], None)

    client = OpenAI(api_key=api_key)
    tools = _build_openai_tool_list()
    audit_log: list[dict[str, Any]] = []
    tool_results_for_narration: dict[str, Any] = {}

    # Build initial input messages (only needed for the first call in a session)
    initial_input: list[dict[str, Any]] = []
    if previous_response_id is None:
        for turn in conversation_history[-8:]:
            if turn["role"] in ("user", "assistant") and isinstance(turn.get("content"), str):
                initial_input.append({"role": turn["role"], "content": turn["content"]})
        initial_input.append({"role": "user", "content": user_query})
    else:
        # With previous_response_id, only the new user turn is needed
        initial_input = [{"role": "user", "content": user_query}]

    current_input: list[dict[str, Any]] = initial_input
    current_prev_id: str | None = previous_response_id
    last_response_id: str | None = previous_response_id
    start_time = time.monotonic()
    max_wall_clock = float(os.getenv("TERRIS_AGENT_TIMEOUT_SECS", "55"))

    for iteration in range(_MAX_AGENT_ITERATIONS):
        if time.monotonic() - start_time > max_wall_clock:
            logger.warning("Terris agent loop hit wall-clock limit after %d iterations", iteration)
            break

        # Build Responses API kwargs
        create_kwargs: dict[str, Any] = {
            "model": model,
            "tools": tools,
            "instructions": _TERRIS_SYSTEM,
            "store": True,
        }

        if current_prev_id:
            create_kwargs["previous_response_id"] = current_prev_id
            create_kwargs["input"] = current_input
        else:
            create_kwargs["input"] = current_input

        # Add reasoning for models that support it (o-series and gpt-5+)
        if any(seg in model for seg in ("o1", "o3", "o4", "gpt-5", "gpt5")):
            create_kwargs["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}

        try:
            resp = client.responses.create(**create_kwargs)  # type: ignore
        except Exception as exc:
            err_str = str(exc)
            # Reasoning not supported by this model — retry without it
            if "reasoning" in err_str.lower() or "unsupported" in err_str.lower():
                create_kwargs.pop("reasoning", None)
                try:
                    resp = client.responses.create(**create_kwargs)  # type: ignore
                except Exception as exc2:
                    _record_provider_failure(exc2)
                    logger.warning("OpenAI Responses API call failed: %s", exc2)
                    # Fall back to chat.completions
                    return _openai_chat_fallback(
                        user_query, conversation_history, client, model, audit_log
                    )
            # Model not found — fall back to gpt-4o
            elif "model" in err_str.lower() and "not found" in err_str.lower():
                create_kwargs["model"] = "gpt-4o"
                create_kwargs.pop("reasoning", None)
                try:
                    resp = client.responses.create(**create_kwargs)  # type: ignore
                except Exception as exc3:
                    _record_provider_failure(exc3)
                    return _openai_chat_fallback(
                        user_query, conversation_history, client, "gpt-4o", audit_log
                    )
            else:
                _record_provider_failure(exc)
                logger.warning("OpenAI Responses API call failed: %s", exc)
                return _openai_chat_fallback(
                    user_query, conversation_history, client, model, audit_log
                )

        last_response_id = resp.id
        current_prev_id = resp.id

        # Extract tool calls and text from the response output
        fn_calls = []
        for item in resp.output:  # type: ignore
            item_type = getattr(item, "type", None)
            if item_type == "function_call":
                fn_calls.append(item)

        if not fn_calls:
            # No tool calls — grab final answer
            final_text = getattr(resp, "output_text", None) or ""
            if not final_text:
                # Fallback: manually extract from output messages
                parts: list[str] = []
                for item in resp.output:  # type: ignore
                    if getattr(item, "type", None) == "message":
                        for block in getattr(item, "content", []):
                            if getattr(block, "type", None) == "output_text":
                                parts.append(block.text)
                final_text = " ".join(parts).strip()
            if final_text:
                _record_provider_success()
                return final_text, audit_log, last_response_id
            break

        # Execute each tool call and collect outputs
        tool_output_items: list[dict[str, Any]] = []
        for tc in fn_calls:
            tool_name = getattr(tc, "name", "")
            call_id = getattr(tc, "call_id", "")
            fn = TERRIS_TOOL_MAP.get(tool_name)
            label = STAGE_PROGRESS_LABELS.get(f"invoke_{tool_name}", f"Reviewing {tool_name.replace('_',' ')}…")

            if on_progress:
                on_progress({"stage": f"agent_invoke_{tool_name}", "label": label, "status": "started"})

            try:
                result = fn() if fn else {"error": f"Unknown tool: {tool_name}"}
                brief = _brief_tool_result(tool_name, result)
                audit_log.append({"iteration": iteration + 1, "tool": tool_name, "status": "completed", "brief": brief})
                tool_results_for_narration[tool_name] = result
                tool_output_items.append({"type": "function_call_output", "call_id": call_id, "output": json.dumps(result)})
                if on_progress:
                    on_progress({"stage": f"agent_invoke_{tool_name}", "label": label, "status": "completed"})
            except Exception as exc:
                audit_log.append({"iteration": iteration + 1, "tool": tool_name, "status": "error", "error": str(exc)[:120]})
                tool_output_items.append({"type": "function_call_output", "call_id": call_id, "output": json.dumps({"error": str(exc)[:80]})})

        # Next iteration: feed tool outputs back
        current_input = tool_output_items  # type: ignore

    # Max iterations or empty answer — synthesise from deterministic result
    _record_provider_failure(RuntimeError("max iterations reached without answer"))
    if tool_results_for_narration:
        from .terris import run_terris_investigation
        inv = run_terris_investigation(user_query)
        return inv.get("direct_answer", "Investigation complete. See evidence trail."), audit_log, last_response_id
    return "Investigation complete. See evidence trail.", audit_log, last_response_id


def _openai_chat_fallback(
    user_query: str,
    conversation_history: list[dict[str, Any]],
    client: Any,
    model: str,
    audit_log: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], str | None]:
    """Fall back to chat.completions when Responses API is unavailable."""
    try:
        chat_messages: list[dict[str, str]] = [{"role": "system", "content": _TERRIS_SYSTEM}]
        for turn in conversation_history[-6:]:
            if turn["role"] in ("user", "assistant") and isinstance(turn.get("content"), str):
                chat_messages.append({"role": turn["role"], "content": turn["content"]})
        chat_messages.append({"role": "user", "content": user_query})
        fallback_resp = client.chat.completions.create(
            model=model if model else "gpt-4o",
            max_tokens=1200,
            messages=chat_messages,  # type: ignore
        )
        answer = fallback_resp.choices[0].message.content or ""
        _record_provider_success()
        return answer, audit_log, None
    except Exception as fb_exc:
        _record_provider_failure(fb_exc)
        return f"Provider call failed: {str(fb_exc)[:120]}", audit_log, None


def _run_agent_loop(
    user_query: str,
    conversation_history: list[dict[str, Any]],
    api_key: str,
    provider: str,
    model: str,
    on_progress: Callable[[dict], None] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Bounded tool-using agent loop.

    LLM selects tools from TERRIS_TOOL_MAP; deterministic backend invokes them.
    Max iterations: _MAX_AGENT_ITERATIONS to bound cost.
    Returns (final_answer, audit_log).
    """
    from .terris import TERRIS_TOOL_MAP

    import anthropic  # type: ignore

    client = anthropic.Anthropic(api_key=api_key)
    tools = _build_anthropic_tool_list()
    audit_log: list[dict[str, Any]] = []

    messages: list[dict[str, Any]] = []
    for turn in conversation_history[-6:]:
        if turn["role"] in ("user", "assistant"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_query})

    tool_results_for_narration: dict[str, Any] = {}

    for iteration in range(_MAX_AGENT_ITERATIONS):
        resp = client.messages.create(
            model=model,
            max_tokens=1200,
            system=_TERRIS_SYSTEM,
            tools=tools,  # type: ignore
            messages=messages,  # type: ignore
        )

        # Handle tool use
        if resp.stop_reason == "tool_use":
            tool_calls = [b for b in resp.content if b.type == "tool_use"]
            tool_results_content: list[dict[str, Any]] = []

            for tc in tool_calls:
                tool_name = tc.name
                fn = TERRIS_TOOL_MAP.get(tool_name)
                label = STAGE_PROGRESS_LABELS.get(f"invoke_{tool_name}", f"Running {tool_name}…")

                if on_progress:
                    on_progress({"stage": f"agent_invoke_{tool_name}", "label": label, "status": "started"})

                try:
                    result = fn() if fn else {"error": f"Unknown tool: {tool_name}"}
                    audit_log.append({
                        "iteration": iteration + 1,
                        "tool": tool_name,
                        "status": "completed",
                        "brief": _brief_tool_result(tool_name, result),
                    })
                    tool_results_for_narration[tool_name] = result
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": _brief_tool_result(tool_name, result),
                    })
                    if on_progress:
                        on_progress({"stage": f"agent_invoke_{tool_name}", "label": label, "status": "completed"})
                except Exception as exc:
                    audit_log.append({
                        "iteration": iteration + 1,
                        "tool": tool_name,
                        "status": "error",
                        "error": str(exc)[:120],
                    })
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": f"Error: {str(exc)[:80]}",
                        "is_error": True,
                    })

            # Append assistant turn with tool use
            messages.append({"role": "assistant", "content": resp.content})  # type: ignore
            messages.append({"role": "user", "content": tool_results_content})  # type: ignore
        else:
            # end_turn — LLM has produced final text
            final_text = "".join(
                b.text for b in resp.content if hasattr(b, "text")
            )
            return final_text, audit_log

    # Max iterations hit — synthesize from what we have
    if tool_results_for_narration:
        from .terris import run_terris_investigation
        inv = run_terris_investigation(user_query)
        return inv.get("direct_answer", "Investigation complete. See evidence trail."), audit_log

    return "Investigation complete. See evidence trail.", audit_log


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

    # Try LLM narration — Ollama Local Intelligence or paid providers
    api_key, provider, model, reasoning_effort = _get_llm_config()
    intent = investigation.get("intent", "other")
    effective_effort = _choose_reasoning_effort(user_query, intent, reasoning_effort)

    llm_mode = "structured_safe"
    narrated_answer = investigation.get("direct_answer", "")
    agent_audit_log: list[dict[str, Any]] = []
    new_previous_response_id: str | None = None

    if provider == "ollama":
        # Local Intelligence Mode — no API key required, no cloud calls
        if on_progress:
            on_progress({"stage": "llm_thinking", "label": "Thinking…", "status": "started"})
        try:
            result_text, agent_audit_log = _run_ollama_agent_loop(
                user_query, history, model, on_progress=on_progress,
            )
            if result_text:
                narrated_answer = result_text
            llm_mode = "local_intelligence"
            if on_progress:
                on_progress({"stage": "llm_thinking", "label": "Thinking…", "status": "completed"})
        except Exception as exc:
            logger.warning("Terris Ollama local inference failed, falling back: %s", exc)
            _record_provider_failure(exc, local=True)

    elif provider == "gemini_demo" and api_key:
        # Gemini Demo Intelligence Mode — free tier, illustrative data only, safety gate active
        if on_progress:
            on_progress({"stage": "llm_thinking", "label": "Thinking…", "status": "started"})
        try:
            result_text, agent_audit_log = _run_gemini_agent_loop(
                user_query, history, api_key, model, on_progress=on_progress,
            )
            if result_text:
                narrated_answer = result_text
                llm_mode = "gemini_demo_intelligence"
            else:
                # Gemini returned empty — safe fallback to structured_safe
                logger.info("Terris Gemini returned empty response; using structured safe fallback.")
                llm_mode = "structured_safe"
            if on_progress:
                on_progress({"stage": "llm_thinking", "label": "Thinking…", "status": "completed"})
        except Exception as exc:
            logger.warning("Terris Gemini inference failed, falling back: %s", exc)
            _record_provider_failure(exc, gemini=True)
            llm_mode = "structured_safe"

    elif api_key:
        # Paid provider — Connected Intelligence Mode
        if on_progress:
            on_progress({"stage": "llm_synthesis", "label": "Synthesizing findings…", "status": "started"})
        try:
            if provider == "anthropic":
                narrated_answer, agent_audit_log = _run_agent_loop(
                    user_query, history, api_key, provider, model, on_progress=on_progress,
                )
            elif provider == "openai":
                prior_response_id = ctx.get("openai_previous_response_id")
                narrated_answer, agent_audit_log, new_previous_response_id = _run_openai_agent_loop(
                    user_query, history, api_key, model, effective_effort,
                    on_progress=on_progress,
                    previous_response_id=prior_response_id,
                )
                if new_previous_response_id:
                    ctx["openai_previous_response_id"] = new_previous_response_id
            else:
                narrated_answer = _llm_narrate(
                    user_query, investigation, history, api_key, provider, model, reasoning_effort,
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
        "agent_audit_log": agent_audit_log,
        "investigation_meta": {
            "intent": intent,
            "answer_type": investigation.get("answer_type"),
            "calculation_version": CALCULATION_VERSION,
            "reasoning_effort_used": effective_effort if (api_key or provider == "ollama") else None,
            "previous_response_id": new_previous_response_id,
            "provider": provider,
            "model": model,
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
