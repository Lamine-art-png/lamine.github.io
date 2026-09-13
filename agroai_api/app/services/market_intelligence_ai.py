"""Grounded AI synthesis for Market Intelligence.

The model explains deterministic evidence; it is never the calculator. Numeric
claims must reference an explicit evidence id whose value matches the claim.
Unsupported numeric claims are rejected and replaced with a deterministic
fallback rather than shown to a customer.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.model_router import ModelRouter

PROMPT_VERSION = "market-intelligence-grounded-2026.09.1"


def _canonical_number(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number.normalize() if number.is_finite() else None


def validate_numeric_grounding(payload: dict[str, Any], evidence: dict[str, str]) -> list[str]:
    """Return validation errors for unsupported structured numeric claims."""
    errors: list[str] = []
    for insight in payload.get("insights") or []:
        if not isinstance(insight, dict):
            errors.append("insight_not_object")
            continue
        for claim in insight.get("numeric_claims") or []:
            if not isinstance(claim, dict):
                errors.append("numeric_claim_not_object")
                continue
            evidence_id = str(claim.get("evidence_id") or "")
            if evidence_id not in evidence:
                errors.append(f"unsupported_evidence:{evidence_id}")
                continue
            expected = _canonical_number(evidence[evidence_id])
            actual = _canonical_number(claim.get("value"))
            if expected is None or actual is None or expected != actual:
                errors.append(f"numeric_mismatch:{evidence_id}")
    return errors


def deterministic_brief(position: dict[str, Any], *, question: str | None = None) -> dict[str, Any]:
    exposed = position.get("exposed_percent")
    margin = position.get("projected_margin_percent")
    warnings = list(position.get("warnings") or [])
    lines: list[str] = []
    if exposed is not None:
        lines.append(f"{exposed}% of expected production remains commercially exposed.")
    if margin is not None:
        lines.append(f"Projected margin is {margin}% under the current structured assumptions.")
    if warnings:
        lines.append("Data or position warnings require review before relying on projected margin.")
    if not lines:
        lines.append("The commercial position is available, but more structured market or cost data is required for a complete margin view.")
    return {
        "status": "deterministic",
        "prompt_version": PROMPT_VERSION,
        "summary": " ".join(lines),
        "insights": [],
        "question": question,
        "model_trace": {"provider": "deterministic", "model": None, "grounded": True},
    }


async def generate_market_brief(
    position: dict[str, Any],
    evidence: dict[str, str],
    *,
    question: str | None = None,
    language: str = "en",
) -> dict[str, Any]:
    router = ModelRouter()
    if router.mode() == "offline":
        return deterministic_brief(position, question=question)

    facts = {
        "position": position,
        "evidence": evidence,
        "question": (question or "What materially matters in this commercial position?")[:1600],
        "response_language": language[:16],
    }
    system = (
        "You are the AGRO-AI Market Intelligence synthesis layer. Explain only the supplied structured facts. "
        "Never invent or calculate financial numbers. Never describe a scenario as a forecast. Never give a direct instruction to buy, sell, "
        "short, or enter a specific derivatives position. Every numeric claim must copy an evidence value exactly and include its evidence_id. "
        "If evidence is incomplete, say so. Return concise enterprise decision-support language."
    )
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "market_intelligence_brief",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "insights": {
                        "type": "array",
                        "maxItems": 3,
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "explanation": {"type": "string"},
                                "importance": {"type": "string", "enum": ["high", "medium", "low"]},
                                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                                "numeric_claims": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "evidence_id": {"type": "string"},
                                            "value": {"type": "string"},
                                        },
                                        "required": ["evidence_id", "value"],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "required": ["title", "explanation", "importance", "evidence_ids", "numeric_claims"],
                            "additionalProperties": False,
                        },
                    },
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "limitations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["summary", "insights", "confidence", "limitations"],
                "additionalProperties": False,
            },
        },
    }
    result, selection = await router.run(
        task="market_intelligence",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": "FACTS\n" + json.dumps(facts, separators=(",", ":"), ensure_ascii=False)},
        ],
        temperature=0.1,
        response_format=schema,
        max_tokens=900,
        timeout_seconds=35,
        max_model_attempts=2,
    )
    if result.status != "ok" or not str(result.content or "").strip():
        fallback = deterministic_brief(position, question=question)
        fallback["model_trace"]["fallback_reason"] = result.error or result.status
        return fallback
    try:
        payload = json.loads(result.content)
    except (TypeError, ValueError, json.JSONDecodeError):
        fallback = deterministic_brief(position, question=question)
        fallback["model_trace"]["fallback_reason"] = "invalid_structured_output"
        return fallback
    errors = validate_numeric_grounding(payload, evidence)
    if errors:
        fallback = deterministic_brief(position, question=question)
        fallback["model_trace"]["fallback_reason"] = "numeric_grounding_failed"
        fallback["model_trace"]["validation_errors"] = errors[:8]
        return fallback
    return {
        "status": "ok",
        "prompt_version": PROMPT_VERSION,
        **payload,
        "question": question,
        "model_trace": {
            "provider": result.provider,
            "model": result.model or selection.model,
            "profile": selection.profile,
            "grounded": True,
        },
    }
