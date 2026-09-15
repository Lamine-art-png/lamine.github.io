"""Grounded AI synthesis for Market Intelligence.

The model explains deterministic evidence; it is never the calculator. Numeric
claims must reference an explicit evidence id whose value matches the claim.
Unsupported numeric claims are rejected and replaced with a deterministic
fallback rather than shown to a customer.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.model_router import ModelRouter

PROMPT_VERSION = "market-intelligence-grounded-2026.09.2"
_TEXT_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?(?:\d[\d,]*)(?:\.\d+)?")
_DERIVATIVES_INSTRUCTION_RE = re.compile(
    r"\b(?:buy|sell|short|long|enter|open|execute)\b.{0,80}\b(?:futures?|options?|swaps?|derivatives?)\b"
    r"|\b(?:futures?|options?|swaps?|derivatives?)\b.{0,80}\b(?:buy|sell|short|long)\b",
    flags=re.IGNORECASE,
)


def _canonical_number(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value).replace(",", ""))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number.normalize() if number.is_finite() else None


def _text_numbers(value: Any) -> list[Decimal]:
    text = str(value or "")
    numbers: list[Decimal] = []
    for match in _TEXT_NUMBER_RE.finditer(text):
        parsed = _canonical_number(match.group(0))
        if parsed is not None:
            numbers.append(parsed)
    return numbers


def validate_numeric_grounding(payload: dict[str, Any], evidence: dict[str, str]) -> list[str]:
    """Return validation errors for unsupported or hidden numeric claims.

    The structured ``numeric_claims`` list is not trusted by itself. Numbers in
    customer-visible summary/title/explanation/limitations must also correspond
    to a validated structured claim. This prevents a model from putting an
    invented number in prose while leaving ``numeric_claims`` empty.
    """
    errors: list[str] = []
    global_claim_numbers: set[Decimal] = set()

    for insight_index, insight in enumerate(payload.get("insights") or []):
        if not isinstance(insight, dict):
            errors.append("insight_not_object")
            continue

        declared_evidence_ids = {
            str(item or "")
            for item in (insight.get("evidence_ids") or [])
            if str(item or "")
        }
        for evidence_id in declared_evidence_ids:
            if evidence_id not in evidence:
                errors.append(f"unsupported_evidence:{evidence_id}")

        insight_claim_numbers: set[Decimal] = set()
        for claim in insight.get("numeric_claims") or []:
            if not isinstance(claim, dict):
                errors.append("numeric_claim_not_object")
                continue
            evidence_id = str(claim.get("evidence_id") or "")
            if evidence_id not in evidence:
                errors.append(f"unsupported_evidence:{evidence_id}")
                continue
            if evidence_id not in declared_evidence_ids:
                errors.append(f"numeric_claim_missing_evidence_id:{evidence_id}")
            expected = _canonical_number(evidence[evidence_id])
            actual = _canonical_number(claim.get("value"))
            if expected is None or actual is None or expected != actual:
                errors.append(f"numeric_mismatch:{evidence_id}")
                continue
            insight_claim_numbers.add(actual)
            global_claim_numbers.add(actual)

        visible_text = " ".join(
            str(insight.get(key) or "")
            for key in ("title", "explanation")
        )
        for number in _text_numbers(visible_text):
            if number not in insight_claim_numbers:
                errors.append(f"unstructured_numeric_claim:insight_{insight_index}:{number}")

    top_level_text = " ".join(
        [str(payload.get("summary") or "")]
        + [str(item or "") for item in (payload.get("limitations") or [])]
    )
    for number in _text_numbers(top_level_text):
        if number not in global_claim_numbers:
            errors.append(f"unstructured_numeric_claim:summary:{number}")

    # Stable ordering and de-duplication keeps audit traces compact.
    return list(dict.fromkeys(errors))


def validate_decision_support_policy(payload: dict[str, Any]) -> list[str]:
    """Reject model output that crosses into personalized derivatives instructions."""
    visible = " ".join(
        [str(payload.get("summary") or "")]
        + [str(item or "") for item in (payload.get("limitations") or [])]
        + [
            " ".join(str(insight.get(key) or "") for key in ("title", "explanation"))
            for insight in (payload.get("insights") or [])
            if isinstance(insight, dict)
        ]
    )
    return ["personalized_derivatives_instruction"] if _DERIVATIVES_INSTRUCTION_RE.search(visible) else []


def deterministic_brief(
    position: dict[str, Any],
    *,
    question: str | None = None,
    language: str = "en",
) -> dict[str, Any]:
    exposed = position.get("exposed_percent")
    margin = position.get("projected_margin_percent")
    warnings = list(position.get("warnings") or [])
    lang = str(language or "en").strip().lower().split("-")[0]
    templates = {
        "en": {
            "exposed": "{value}% of expected production remains commercially exposed.",
            "margin": "Projected margin is {value}% under the current structured assumptions.",
            "warning": "Data or position warnings require review before relying on projected margin.",
            "missing": "The commercial position is available, but more structured market or cost data is required for a complete margin view.",
        },
        "fr": {
            "exposed": "{value}% de la production attendue reste exposée commercialement.",
            "margin": "La marge projetée est de {value}% selon les hypothèses structurées actuelles.",
            "warning": "Les alertes de données ou de position doivent être examinées avant de s'appuyer sur la marge projetée.",
            "missing": "La position commerciale est disponible, mais des données de marché ou de coûts plus structurées sont nécessaires pour une vue complète de la marge.",
        },
        "es": {
            "exposed": "El {value}% de la producción esperada sigue expuesta comercialmente.",
            "margin": "El margen proyectado es del {value}% con los supuestos estructurados actuales.",
            "warning": "Las alertas de datos o de posición deben revisarse antes de confiar en el margen proyectado.",
            "missing": "La posición comercial está disponible, pero se necesitan más datos estructurados de mercado o costes para completar la visión del margen.",
        },
        "pt": {
            "exposed": "{value}% da produção esperada permanece comercialmente exposta.",
            "margin": "A margem projetada é de {value}% sob as premissas estruturadas atuais.",
            "warning": "Alertas de dados ou de posição precisam ser revisados antes de confiar na margem projetada.",
            "missing": "A posição comercial está disponível, mas são necessários mais dados estruturados de mercado ou custos para uma visão completa da margem.",
        },
    }
    copy = templates.get(lang, templates["en"])
    lines: list[str] = []
    if exposed is not None:
        lines.append(copy["exposed"].format(value=exposed))
    if margin is not None:
        lines.append(copy["margin"].format(value=margin))
    if warnings:
        lines.append(copy["warning"])
    if not lines:
        lines.append(copy["missing"])
    return {
        "status": "deterministic",
        "prompt_version": PROMPT_VERSION,
        "summary": " ".join(lines),
        "insights": [],
        "question": question,
        "response_language": lang,
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
        return deterministic_brief(position, question=question, language=language)

    facts = {
        "position": position,
        "evidence": evidence,
        "question": (question or "What materially matters in this commercial position?")[:1600],
        "response_language": language[:16],
    }
    system = (
        "You are the AGRO-AI Market Intelligence synthesis layer. Explain only the supplied structured facts. "
        "Never invent or calculate financial numbers. Never describe a scenario as a forecast. Never give a direct instruction to buy, sell, "
        "short, or enter a specific derivatives position. Every numeric claim must copy an evidence value exactly, include its evidence_id in "
        "numeric_claims, and include that same id in evidence_ids. Do not put any number in summary, title, explanation, or limitations unless it "
        "is represented by a numeric_claim. Respond in FACTS.response_language. If evidence is incomplete, say so. Return concise enterprise "
        "decision-support language."
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
        fallback = deterministic_brief(position, question=question, language=language)
        fallback["model_trace"]["fallback_reason"] = result.error or result.status
        return fallback
    try:
        payload = json.loads(result.content)
    except (TypeError, ValueError, json.JSONDecodeError):
        fallback = deterministic_brief(position, question=question, language=language)
        fallback["model_trace"]["fallback_reason"] = "invalid_structured_output"
        return fallback
    grounding_errors = validate_numeric_grounding(payload, evidence)
    policy_errors = validate_decision_support_policy(payload)
    errors = grounding_errors + policy_errors
    if errors:
        fallback = deterministic_brief(position, question=question, language=language)
        fallback["model_trace"]["fallback_reason"] = (
            "decision_support_policy_failed" if policy_errors else "numeric_grounding_failed"
        )
        fallback["model_trace"]["validation_errors"] = errors[:8]
        return fallback
    return {
        "status": "ok",
        "prompt_version": PROMPT_VERSION,
        **payload,
        "question": question,
        "response_language": str(language or "en")[:16],
        "model_trace": {
            "provider": result.provider,
            "model": result.model or selection.model,
            "profile": selection.profile,
            "grounded": True,
        },
    }
