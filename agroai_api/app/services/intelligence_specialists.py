"""Side-effect-free specialist intelligence cells.

Specialists organize evidence and deterministic science for a narrow domain.
They cannot approve, schedule, execute, submit, or change controller state.
Their only proposed next steps are inspection or evidence collection.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.intelligence_grounding import EvidenceSignal, IntelligenceGroundingPacket
from app.services.scientific_tool_registry import get_scientific_tool_registry


SpecialistDomain = Literal["water", "crop_health", "equipment", "assurance", "reporting"]
SafeSpecialistActionKind = Literal["inspection", "data_collection"]


class SpecialistAction(BaseModel):
    action: str
    action_kind: SafeSpecialistActionKind
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)


class SpecialistResult(BaseModel):
    domain: SpecialistDomain
    status: Literal["evidence_available", "evidence_limited", "conflict_review"]
    observed_evidence: list[dict[str, Any]] = Field(default_factory=list)
    deterministic_findings: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    next_evidence_actions: list[SpecialistAction] = Field(default_factory=list)
    confidence_cap: float = Field(ge=0, le=1)
    side_effect_free: bool = True


_DOMAIN_SOURCE_TYPES: dict[SpecialistDomain, set[str]] = {
    "water": {"telemetry", "telemetry_recent", "weather", "weather_observation", "sensor", "meter_reading"},
    "crop_health": {"field_observation", "image_observation", "operator_note", "sensor"},
    "equipment": {"telemetry", "telemetry_recent", "meter_reading", "field_observation", "operator_note"},
    "assurance": {"field_observation", "operator_note", "uploaded_file"},
    "reporting": set(),
}
_DOMAIN_TERMS: dict[SpecialistDomain, tuple[str, ...]] = {
    "water": ("water", "irrigat", "moisture", "vwc", "eto", "et0", "rain", "precip", "flow", "runtime", "root zone", "root-zone", "depletion"),
    "crop_health": ("crop", "leaf", "canopy", "pest", "disease", "lesion", "stress", "symptom", "plant", "fruit"),
    "equipment": ("equipment", "controller", "valve", "pump", "pressure", "motor", "machine", "flow meter", "offline", "fault"),
    "assurance": ("compliance", "assurance", "audit", "trace", "record", "regulator", "sgma", "label", "requirement"),
    "reporting": (),
}
_SCIENCE_DOMAINS: dict[SpecialistDomain, set[str]] = {
    "water": {"crop_water", "soil_water", "water_balance", "irrigation_measurement", "irrigation_planning"},
    "crop_health": {"phenology"},
    "equipment": {"irrigation_measurement", "evidence_quality"},
    "assurance": {"nutrient_accounting", "evidence_quality"},
    "reporting": {"crop_water", "soil_water", "water_balance", "irrigation_measurement", "irrigation_planning", "phenology", "nutrient_accounting", "evidence_quality", "units"},
}


def _text(signal: EvidenceSignal) -> str:
    return f"{signal.title} {signal.statement} {signal.source_type}".casefold()


def _relevant_signal(domain: SpecialistDomain, signal: EvidenceSignal) -> bool:
    if domain == "reporting":
        return True
    source = str(signal.source_type or "").casefold()
    if source in _DOMAIN_SOURCE_TYPES[domain]:
        text = _text(signal)
        if any(term in text for term in _DOMAIN_TERMS[domain]):
            return True
        if domain == "water" and source in {"weather", "weather_observation", "meter_reading"}:
            return True
    return any(term in _text(signal) for term in _DOMAIN_TERMS[domain])


def _relevant_unknown(domain: SpecialistDomain, value: str) -> bool:
    if domain == "reporting":
        return True
    text = str(value or "").casefold()
    return any(term in text for term in _DOMAIN_TERMS[domain])


def _science_domain(rule_id: str) -> str | None:
    registry = get_scientific_tool_registry()
    try:
        return registry.spec(rule_id).domain
    except KeyError:
        return None


def _evidence_entry(signal: EvidenceSignal) -> dict[str, Any]:
    return {
        "evidence_id": signal.evidence_id,
        "source_type": signal.source_type,
        "title": signal.title,
        "statement": signal.statement,
        "observed_at": signal.observed_at,
        "confidence": signal.confidence_score,
        "quality": signal.quality_score,
        "freshness": signal.freshness_score,
        "operational_eligible": signal.provenance.get("operational_eligible") is True,
    }


def _safe_next_actions(
    domain: SpecialistDomain,
    packet: IntelligenceGroundingPacket,
    evidence_ids: list[str],
    unknowns: list[str],
) -> list[SpecialistAction]:
    actions: list[SpecialistAction] = []
    if packet.conflicts:
        relevant_conflicts = [
            conflict
            for conflict in packet.conflicts
            if domain == "reporting"
            or any(eid in evidence_ids for eid in conflict.evidence_ids)
            or any(term in conflict.metric.casefold() for term in _DOMAIN_TERMS[domain])
        ]
        if relevant_conflicts:
            actions.append(
                SpecialistAction(
                    action="Inspect the conflicting source readings and confirm which source is valid for the current field scope.",
                    action_kind="inspection",
                    reason="Conflicting evidence must be resolved before confidence can increase.",
                    evidence_ids=sorted({eid for conflict in relevant_conflicts for eid in conflict.evidence_ids}),
                )
            )
    if unknowns:
        domain_request = {
            "water": "Collect the missing field-scoped water, weather, soil, or system measurement required by the deterministic calculation.",
            "crop_health": "Collect a geotagged follow-up field observation or image with crop, location, time, and symptom context.",
            "equipment": "Inspect equipment state and collect controller, pressure, flow, or fault evidence with a timestamp and field/block identity.",
            "assurance": "Collect the missing authoritative record, label, transaction, or verification artifact before making an assurance claim.",
            "reporting": "Collect or reconcile the missing source records before publishing a definitive report statement.",
        }[domain]
        actions.append(
            SpecialistAction(
                action=domain_request,
                action_kind="data_collection",
                reason="The current evidence graph contains unresolved unknowns for this domain.",
                evidence_ids=evidence_ids,
            )
        )
    if not evidence_ids and not actions:
        actions.append(
            SpecialistAction(
                action="Collect field-scoped evidence for this domain before drawing a conclusion.",
                action_kind="data_collection",
                reason="No relevant observed evidence is available in the current graph.",
                evidence_ids=[],
            )
        )
    return actions[:3]


def analyze_specialist(domain: SpecialistDomain, packet: IntelligenceGroundingPacket) -> SpecialistResult:
    signals = [signal for signal in packet.observed_facts if _relevant_signal(domain, signal)]
    evidence_ids = [signal.evidence_id for signal in signals]
    science: list[dict[str, Any]] = []
    for result in packet.science_checks:
        science_domain = _science_domain(result.rule_id)
        if result.status == "computed" and science_domain in _SCIENCE_DOMAINS[domain]:
            science.append(
                {
                    "rule_id": result.rule_id,
                    "name": result.name,
                    "value": result.value,
                    "unit": result.unit,
                    "evidence_ids": result.evidence_ids,
                    "confidence": result.confidence_score,
                    "limitations": result.limitations,
                }
            )
    conflicts = []
    for conflict in packet.conflicts:
        if (
            domain == "reporting"
            or any(eid in evidence_ids for eid in conflict.evidence_ids)
            or any(term in conflict.metric.casefold() for term in _DOMAIN_TERMS[domain])
        ):
            conflicts.append(conflict.model_dump(mode="python"))
    unknowns = [value for value in packet.unknowns if _relevant_unknown(domain, value)]
    if conflicts:
        status = "conflict_review"
    elif signals or science:
        status = "evidence_available"
    else:
        status = "evidence_limited"
    confidence_cap = packet.grounding_confidence
    if conflicts:
        confidence_cap = min(confidence_cap, 0.60)
    if not signals and not science:
        confidence_cap = min(confidence_cap, 0.30)
    return SpecialistResult(
        domain=domain,
        status=status,
        observed_evidence=[_evidence_entry(signal) for signal in signals[:30]],
        deterministic_findings=science[:20],
        conflicts=conflicts[:20],
        unknowns=unknowns[:20],
        next_evidence_actions=_safe_next_actions(domain, packet, evidence_ids, unknowns),
        confidence_cap=round(max(0.05, confidence_cap), 3),
        side_effect_free=True,
    )


def run_specialists(
    packet: IntelligenceGroundingPacket,
    domains: list[SpecialistDomain] | None = None,
) -> list[SpecialistResult]:
    selected = domains or ["water", "crop_health", "equipment", "assurance", "reporting"]
    return [analyze_specialist(domain, packet) for domain in selected]
