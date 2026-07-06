from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


_NUMBER_RE = re.compile(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?(?![\w])")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_OPERATIONAL_RE = re.compile(
    r"\b(?:irrigat\w*|apply|increase|decrease|stop|start|open|close|run|dose|inject|"
    r"water|schedule|execute|send|approve|appliquer|irriguer|arrêter|arreter|ouvrir|fermer|"
    r"regar|aplicar|detener|abrir|cerrar|irrigar|parar|aumentar|diminuir)\b",
    re.IGNORECASE,
)
_OPERATIONAL_QUESTION_RE = re.compile(
    r"\b(?:how much water|irrigat\w*|water should|apply|schedule|execute|decision|"
    r"combien d['’]eau|irriguer|cu[aá]nta agua|regar|quanta [aá]gua|irrigar)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ClaimSupport:
    claim: str
    operational: bool
    numeric_values: tuple[str, ...]
    status: str
    reason: str


@dataclass(frozen=True)
class DecisionSafetyEnvelope:
    status: str
    operational_intent: bool
    execution_candidate: bool
    approval_required: bool
    sample_mode: bool
    evidence_count: int
    citation_count: int
    missing_requirements: tuple[str, ...]
    claims: tuple[ClaimSupport, ...]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "operational_intent": self.operational_intent,
            "execution_candidate": self.execution_candidate,
            "approval_required": self.approval_required,
            "sample_mode": self.sample_mode,
            "evidence_count": self.evidence_count,
            "citation_count": self.citation_count,
            "missing_requirements": list(self.missing_requirements),
            "claims": [asdict(item) for item in self.claims],
            "reasons": list(self.reasons),
        }


def _normalize_number(value: str) -> str:
    try:
        number = Decimal(value.replace(",", "."))
    except InvalidOperation:
        return value
    normalized = format(number.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _numbers(text: str) -> tuple[str, ...]:
    return tuple(_normalize_number(match.group(0)) for match in _NUMBER_RE.finditer(text or ""))


def _evidence_corpus(context: Any) -> str:
    citations = [
        item.model_dump(mode="python") if hasattr(item, "model_dump") else item
        for item in getattr(context, "citations", [])
    ]
    return json.dumps(
        {
            "evidence": getattr(context, "evidence", []),
            "citations": citations,
        },
        ensure_ascii=False,
        default=str,
        sort_keys=True,
    )


def _has_live_operational_recommendation(context: Any) -> bool:
    for item in getattr(context, "evidence", []):
        if not isinstance(item, dict) or item.get("type") != "recommendation_recent":
            continue
        meta = item.get("meta_data") or item.get("metadata") or {}
        record = item.get("record") or item
        if bool(meta.get("operational_use")) or bool((record.get("meta_data") or {}).get("operational_use")):
            return True
    return False


def _claim_support(answer: str, evidence_corpus: str) -> tuple[ClaimSupport, ...]:
    evidence_numbers = set(_numbers(evidence_corpus))
    claims: list[ClaimSupport] = []
    for raw in _SENTENCE_RE.split(answer or ""):
        claim = raw.strip()
        if not claim:
            continue
        numbers = _numbers(claim)
        operational = bool(_OPERATIONAL_RE.search(claim))
        missing_numbers = [value for value in numbers if value not in evidence_numbers]
        if missing_numbers:
            status = "unsupported"
            reason = f"numeric values not found in evidence: {', '.join(missing_numbers)}"
        elif numbers:
            status = "evidence_matched"
            reason = "all numeric values appear in the evidence corpus"
        elif operational:
            status = "requires_operational_record"
            reason = "operational claim requires a live operational recommendation record"
        else:
            status = "narrative_unverified"
            reason = "narrative claim is not promoted to an operational fact"
        claims.append(ClaimSupport(claim, operational, numbers, status, reason))
    return tuple(claims[:40])


def evaluate_decision_safety(
    *,
    task: str,
    question: str,
    answer: str,
    context: Any,
    sample_mode: bool,
) -> DecisionSafetyEnvelope:
    operational_intent = task in {
        "irrigation_plan", "irrigation_recommendation", "decision_workbench",
        "field_diagnosis", "execution", "action",
    } or bool(_OPERATIONAL_QUESTION_RE.search(question or ""))

    evidence = list(getattr(context, "evidence", []) or [])
    citations = list(getattr(context, "citations", []) or [])
    missing = tuple(str(item) for item in getattr(context, "missing_data", []) or [] if str(item).strip())
    live_operational_record = _has_live_operational_recommendation(context)
    claims = _claim_support(answer, _evidence_corpus(context))

    unsupported_numeric = any(item.status == "unsupported" for item in claims)
    operational_claims = [item for item in claims if item.operational]
    reasons: list[str] = []

    if sample_mode:
        reasons.append("sample/evaluation data cannot authorize a live operating decision")
    if missing:
        reasons.append("required evidence is missing")
    if unsupported_numeric:
        reasons.append("one or more numeric claims are not present in the evidence corpus")
    if operational_intent and not live_operational_record:
        reasons.append("no live operational recommendation record authorizes the proposed action")
    if operational_intent and len(citations) < 1:
        reasons.append("no citation evidence is attached to the operating context")

    execution_candidate = bool(
        operational_intent
        and not sample_mode
        and not missing
        and not unsupported_numeric
        and live_operational_record
        and citations
    )

    if execution_candidate:
        status = "approval_required"
    elif operational_intent:
        status = "blocked"
    else:
        status = "advisory"

    if operational_claims and not execution_candidate:
        reasons.append("operational language remains advisory until deterministic evidence gates pass")

    return DecisionSafetyEnvelope(
        status=status,
        operational_intent=operational_intent,
        execution_candidate=execution_candidate,
        approval_required=execution_candidate,
        sample_mode=sample_mode,
        evidence_count=len(evidence),
        citation_count=len(citations),
        missing_requirements=missing,
        claims=claims,
        reasons=tuple(dict.fromkeys(reasons)),
    )
