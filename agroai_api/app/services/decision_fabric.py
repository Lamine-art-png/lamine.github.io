"""Shared hidden decision fabric for AGRO-AI multimodal intelligence.

The fabric is a bounded probabilistic routing layer. It never becomes evidence,
does not calculate agronomic/financial truth, and cannot authorize execution.
It consumes only compact redacted/aggregate state and returns qualitative
routing guidance to existing AGRO-AI intelligence surfaces.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.decision_model import assist_enabled, decision_model_config

logger = logging.getLogger("uvicorn.error")

_ALLOWED_ROUTES = {"act", "review", "collect_evidence", "monitor", "defer"}
_OPERATIONAL_TASKS = {
    "chat",
    "chat_fast",
    "deep_analysis",
    "field_diagnosis",
    "irrigation_recommendation",
    "exception_triage",
    "gap_analysis",
    "decision_workbench",
    "readiness_analysis",
    "assurance_review",
    "report_factory",
    "report_draft",
    "connector_diagnosis",
    "integration_diagnosis",
    "market_intelligence",
    "crop_risk",
    "evidence_analysis",
    "decision",
    "report",
    "readiness_refresh",
    "proof_draft",
}
_CASUAL_RE = re.compile(
    r"^\s*(?:hi|hello|hey|yo|bonjour|salut|hola|ol[aá]|thanks?|thank you|merci|gracias|obrigad[oa])[!.?\s]*$",
    re.IGNORECASE,
)
_PHYSICAL_RE = re.compile(
    r"\b(?:irrigat\w*|water|pump|valve|controller|spray|apply|dose|inject|start|stop|open|close|execute)\b",
    re.IGNORECASE,
)
_EVIDENCE_RE = re.compile(
    r"\b(?:evidence|proof|verify|verification|audit|compliance|report|diagnos\w*|inspect|missing|uncertain|conflict)\b",
    re.IGNORECASE,
)
_EXTERNAL_RE = re.compile(
    r"\b(?:send|email|message|publish|submit|trade|buy|sell|contract|order)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DecisionAdvisory:
    route: str
    route_confidence: float
    urgency_score: float
    urgency_confidence: float
    needs_human_review: float
    data_sufficient: float
    should_act_now: float

    def safe_dict(self) -> dict[str, Any]:
        """Provider-neutral metadata safe for internal model context.

        Scores are intentionally converted into coarse booleans/bands before the
        advisory joins any downstream prompt. This prevents a routing model's
        confidence from being mistaken for evidence confidence.
        """
        return {
            "route": self.route,
            "urgency": _band(self.urgency_score),
            "requires_human_review": self.needs_human_review >= 0.70,
            "evidence_sufficient": self.data_sufficient >= 0.65,
            "act_now": self.should_act_now >= 0.70,
            "advisory_only": True,
            "not_evidence": True,
            "not_authorization": True,
        }


def _probability(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _band(value: float) -> str:
    if value >= 0.80:
        return "high"
    if value >= 0.45:
        return "medium"
    return "low"


def _count(value: Any, *, cap: int = 999) -> int:
    try:
        return max(0, min(cap, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def _confidence_band(value: Any) -> str:
    try:
        score = max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return "unknown"
    if score >= 0.80:
        return "high"
    if score >= 0.50:
        return "medium"
    return "low"


def should_invoke(task: str | None, question: str | None = None) -> bool:
    task_name = str(task or "").strip().lower()
    if task_name and task_name not in _OPERATIONAL_TASKS:
        return False
    text = str(question or "").strip()
    if text and _CASUAL_RE.fullmatch(text):
        return False
    return True


def intent_flags(question: str | None, task: str | None = None) -> dict[str, bool]:
    text = str(question or "")[:4000]
    return {
        "physical_or_operational_action": bool(_PHYSICAL_RE.search(text)),
        "evidence_or_review": bool(_EVIDENCE_RE.search(text)),
        "external_or_commercial_action": bool(_EXTERNAL_RE.search(text)),
        "deep_or_decision_task": str(task or "").strip().lower()
        in {
            "deep_analysis",
            "field_diagnosis",
            "irrigation_recommendation",
            "decision_workbench",
            "crop_risk",
            "decision",
            "assurance_review",
            "evidence_analysis",
        },
    }


def _sanitize_state(value: Any, *, depth: int = 0) -> Any:
    """Recursively minimize provider-bound state.

    Only bounded structured routing signals are expected. This final boundary
    strips identifiers/secrets even if a future caller accidentally supplies
    them and truncates free-form strings.
    """
    if depth > 6:
        return None
    blocked = {
        "organization_id", "tenant_id", "workspace_id", "field_id", "block_id",
        "user_id", "email", "name", "filename", "provider", "model", "question",
        "transcript", "summary", "raw", "api_key", "apikey", "secret", "token",
        "password", "credential", "authorization", "location", "coordinates",
        "latitude", "longitude",
    }
    if isinstance(value, dict):
        return {
            str(key)[:80]: _sanitize_state(item, depth=depth + 1)
            for key, item in value.items()
            if str(key).lower() not in blocked
            and not any(part in str(key).lower() for part in ("secret", "token", "password", "credential", "api_key"))
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_state(item, depth=depth + 1) for item in list(value)[:50]]
    if isinstance(value, str):
        return value[:160]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:160]


def _questions(surface: str) -> dict[str, Any]:
    surface_label = {
        "grounded_intelligence": "an evidence-grounded agricultural intelligence request",
        "generic_intelligence": "an agricultural software intelligence request",
        "field_intelligence": "a field observation",
        "crop_intelligence": "a crop and commercial intelligence state",
        "market_intelligence": "a crop and commercial intelligence state",
        "action_planning": "a proposed agricultural software action",
    }.get(surface, "an agricultural intelligence state")
    return {
        "route": {
            "type": "choice",
            "instructions": (
                f"Choose the safest useful routing for {surface_label}. "
                "Use only the supplied structured state. Do not invent facts. "
                "Prefer collect_evidence or review when evidence is weak/conflicting."
            ),
            "criteria": {
                "act": "Enough evidence exists to advance a non-authorizing next step now.",
                "review": "A human should review before a consequential conclusion or action.",
                "collect_evidence": "More or better evidence is the next useful step.",
                "monitor": "No immediate intervention is indicated; continue observing.",
                "defer": "The state is too weak or irrelevant for a useful decision now.",
            },
        },
        "urgency": {
            "type": "score",
            "instructions": "How urgent is attention to this state?",
            "criteria": [
                "No meaningful urgency.",
                "Routine follow-through.",
                "Attention is warranted soon.",
                "Immediate review or follow-through is warranted.",
            ],
        },
        "needs_human_review": {
            "type": "noul",
            "instructions": "A human should review before any consequential operational or external action.",
        },
        "data_sufficient": {
            "type": "noul",
            "instructions": "The supplied structured evidence is sufficient for the next bounded decision step.",
        },
        "should_act_now": {
            "type": "noul",
            "instructions": "The state warrants a concrete next step now rather than passive monitoring.",
        },
    }


def _parse(body: dict[str, Any]) -> DecisionAdvisory | None:
    answers = body.get("answers")
    if not isinstance(answers, dict):
        return None
    route = answers.get("route") if isinstance(answers.get("route"), dict) else {}
    urgency = answers.get("urgency") if isinstance(answers.get("urgency"), dict) else {}
    review = answers.get("needs_human_review") if isinstance(answers.get("needs_human_review"), dict) else {}
    sufficient = answers.get("data_sufficient") if isinstance(answers.get("data_sufficient"), dict) else {}
    act = answers.get("should_act_now") if isinstance(answers.get("should_act_now"), dict) else {}

    route_value = str(route.get("choice") or "defer")
    if route_value not in _ALLOWED_ROUTES:
        route_value = "defer"
    try:
        urgency_score = max(0.0, min(1.0, float(urgency.get("score", 0.0)) / 3.0))
    except (TypeError, ValueError):
        urgency_score = 0.0
    return DecisionAdvisory(
        route=route_value,
        route_confidence=_probability(route.get("confidence")),
        urgency_score=urgency_score,
        urgency_confidence=_probability(urgency.get("confidence")),
        needs_human_review=_probability(review.get("noul")),
        data_sufficient=_probability(sufficient.get("noul")),
        should_act_now=_probability(act.get("noul")),
    )


def assess_surface(surface: str, state: dict[str, Any]) -> DecisionAdvisory | None:
    """Evaluate redacted structured state and always fail open.

    This fabric is optional intelligence. Any configuration, serialization,
    transport, provider, or parsing failure returns None so the existing
    AGRO-AI stack remains fully operational.
    """
    try:
        config = decision_model_config()
        if not config.configured:
            return None

        safe_state = _sanitize_state(state)
        payload = {
            "state": json.dumps(safe_state, sort_keys=True, separators=(",", ":"), default=str)[:12000],
            "model": config.model,
            "questions": _questions(surface),
        }
        response = httpx.post(
            f"{config.base_url}/v1/systemone",
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "agroai-decision-fabric/1.0",
            },
            json=payload,
            timeout=config.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            return None
        advisory = _parse(body)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "decision_fabric_unavailable surface=%s error_type=%s",
            surface,
            exc.__class__.__name__,
        )
        return None

    if advisory is not None:
        logger.info(
            "decision_fabric_evaluation surface=%s route=%s route_confidence=%.4f urgency=%.4f human_review=%.4f data_sufficient=%.4f act_now=%.4f mode=%s",
            surface,
            advisory.route,
            advisory.route_confidence,
            advisory.urgency_score,
            advisory.needs_human_review,
            advisory.data_sufficient,
            advisory.should_act_now,
            config.mode,
        )
    return advisory


def grounding_state(packet: Any, *, task: str, question: str) -> dict[str, Any]:
    science = list(getattr(packet, "science_checks", []) or [])
    return {
        "surface": "grounded_intelligence",
        "task": str(task or "")[:80],
        "observed_fact_count": _count(len(list(getattr(packet, "observed_facts", []) or []))),
        "derived_context_count": _count(len(list(getattr(packet, "derived_context", []) or []))),
        "unknown_count": _count(len(list(getattr(packet, "unknowns", []) or []))),
        "conflict_count": _count(len(list(getattr(packet, "conflicts", []) or []))),
        "computed_science_count": _count(sum(1 for row in science if getattr(row, "status", None) == "computed")),
        "incomplete_science_count": _count(sum(1 for row in science if getattr(row, "status", None) != "computed")),
        "grounding_confidence": _confidence_band(getattr(packet, "grounding_confidence", None)),
        "decision_constraint_count": _count(len(list(getattr(packet, "decision_constraints", []) or []))),
        "intent": intent_flags(question, task),
    }


def attach_grounding_advisory(packet: Any, *, task: str, question: str) -> DecisionAdvisory | None:
    try:
        if not should_invoke(task, question):
            return None
        advisory = assess_surface("grounded_intelligence", grounding_state(packet, task=task, question=question))
        if advisory is None:
            return None

        # Shadow mode observes and logs only. It must not modify model context.
        if assist_enabled():
            source_health = getattr(packet, "source_health", None)
            if isinstance(source_health, dict):
                source_health["decision_routing"] = advisory.safe_dict()

            constraints = list(getattr(packet, "decision_constraints", []) or [])
            if advisory.data_sufficient < 0.50:
                constraints.append(
                    "Internal decision routing indicates that more evidence is needed before a definitive consequential recommendation."
                )
            if advisory.needs_human_review >= 0.70:
                constraints.append(
                    "Internal decision routing requires human review before any consequential operational or external action."
                )
            packet.decision_constraints = list(dict.fromkeys(constraints))
        return advisory
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "decision_fabric_grounding_hook_failed error_type=%s",
            exc.__class__.__name__,
        )
        return None


def evidence_context_state(context: Any, *, task: str, question: str) -> dict[str, Any]:
    evidence = list(getattr(context, "evidence", []) or [])
    missing = list(getattr(context, "missing_data", []) or [])
    citations = list(getattr(context, "citations", []) or [])
    return {
        "surface": "generic_intelligence",
        "task": str(task or "")[:80],
        "evidence_item_count": _count(len(evidence)),
        "missing_data_count": _count(len(missing)),
        "citation_count": _count(len(citations)),
        "has_missing_data": bool(missing),
        "has_evidence": bool(evidence),
        "intent": intent_flags(question, task),
    }


def assess_evidence_context(context: Any, *, task: str, question: str) -> DecisionAdvisory | None:
    if not should_invoke(task, question):
        return None
    return assess_surface(
        "generic_intelligence",
        evidence_context_state(context, task=task, question=question),
    )


def advisory_context(advisory: DecisionAdvisory | None) -> dict[str, Any] | None:
    if advisory is None or not assist_enabled():
        return None
    return advisory.safe_dict()


def advisory_prompt(advisory: DecisionAdvisory | None) -> str:
    safe = advisory_context(advisory)
    if safe is None:
        return ""
    return (
        "INTERNAL DECISION ROUTING ADVISORY (never cite or expose as a customer fact): "
        f"route={safe['route']}; urgency={safe['urgency']}; "
        f"human_review_required={str(safe['requires_human_review']).lower()}; "
        f"evidence_sufficient={str(safe['evidence_sufficient']).lower()}; "
        f"act_now={str(safe['act_now']).lower()}. "
        "This is not evidence, not agronomic/financial truth, and not authorization. "
        "Use it only to choose whether to answer, request evidence, recommend review, or prioritize the next safe step. "
        "Existing evidence, deterministic calculations, policy, permissions, and approval gates remain authoritative."
    )


def field_observation_state(
    *,
    confidence: Any,
    uncertain_count: int,
    evidence_count: int,
    severity: str | None,
    has_text: bool,
    has_recommended_action: bool,
    has_correlation: bool,
) -> dict[str, Any]:
    severity_value = str(severity or "unknown").lower()
    if severity_value not in {"info", "low", "medium", "high", "critical"}:
        severity_value = "unknown"
    return {
        "surface": "field_intelligence",
        "extraction_confidence": _confidence_band(confidence),
        "uncertain_field_count": _count(uncertain_count),
        "correlated_evidence_count": _count(evidence_count),
        "severity": severity_value,
        "has_confirmed_text": bool(has_text),
        "has_recommended_follow_up": bool(has_recommended_action),
        "has_correlation": bool(has_correlation),
    }


def assess_field_observation(**kwargs: Any) -> DecisionAdvisory | None:
    return assess_surface("field_intelligence", field_observation_state(**kwargs))


def field_requires_review(advisory: DecisionAdvisory | None) -> bool:
    if advisory is None or not assist_enabled():
        return False
    return advisory.needs_human_review >= 0.70 or advisory.data_sufficient < 0.50


def safe_field_follow_up(advisory: DecisionAdvisory | None) -> str | None:
    if advisory is None or not assist_enabled():
        return None
    if advisory.route == "collect_evidence":
        return "Collect or verify additional field evidence before taking consequential operational action."
    if advisory.route == "review":
        return "Review this observation before any consequential field action."
    if advisory.route == "monitor":
        return "Continue monitoring and capture a new observation if conditions change."
    return None


def market_state(position: dict[str, Any], evidence: dict[str, Any], *, question: str | None = None) -> dict[str, Any]:
    health = position.get("data_health") if isinstance(position.get("data_health"), dict) else {}
    warnings = list(position.get("warnings") or [])
    missing_fields = list(position.get("missing_fields") or [])
    return {
        "surface": "crop_intelligence",
        "data_health": str(health.get("status") or "unknown")[:40],
        "warning_count": _count(len(warnings)),
        "missing_field_count": _count(len(missing_fields)),
        "evidence_value_count": _count(len(evidence or {})),
        "has_projected_margin": position.get("projected_margin") is not None,
        "has_exposure_measure": position.get("exposed_percent") is not None,
        "has_contract_coverage": position.get("contracted_percent") is not None,
        "intent": intent_flags(question, "crop_risk"),
    }


def assess_market_position(
    position: dict[str, Any],
    evidence: dict[str, Any],
    *,
    question: str | None = None,
) -> DecisionAdvisory | None:
    return assess_surface(
        "crop_intelligence",
        market_state(position, evidence, question=question),
    )
