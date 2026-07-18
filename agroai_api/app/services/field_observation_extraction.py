"""Schema-constrained structured extraction for field observations.

Replaces ad hoc regex-only behavior with a strict Pydantic schema plus a
deterministic fallback extractor. Model-provider logic stays out of routes and
never fabricates a field, block, measurement or timestamp: anything not clearly
present in the text is recorded as uncertain and left null.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Version the schema + deterministic prompt/rules so provenance is auditable.
EXTRACTION_SCHEMA_VERSION = "field-observation-extraction/1.0.0"
EXTRACTION_METHOD_DETERMINISTIC = "deterministic-v1"

EventType = Literal[
    "observation",
    "irrigation_event",
    "issue",
    "meter_reading",
    "pest_disease",
    "equipment",
    "compliance_note",
    "operator_note",
]
Severity = Literal["info", "low", "medium", "high", "critical"]


class Measurement(BaseModel):
    label: str
    value: float
    unit: str
    uncertain: bool = False


class FieldObservationExtraction(BaseModel):
    """Strict, provenance-bearing extraction output."""

    event_type: EventType = "observation"
    field_candidate: Optional[str] = None
    block_candidate: Optional[str] = None
    crop: Optional[str] = None
    issue: Optional[str] = None
    severity: Severity = "info"
    measurements: list[Measurement] = Field(default_factory=list)
    irrigation_duration_minutes: Optional[float] = None
    applied_water_gallons: Optional[float] = None
    flow_rate_gpm: Optional[float] = None
    equipment: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    occurrence_time: Optional[datetime] = None
    recommended_follow_up: Optional[str] = None
    evidence_requirements: list[str] = Field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0
    uncertain_fields: list[str] = Field(default_factory=list)
    method: str = EXTRACTION_METHOD_DETERMINISTIC
    schema_version: str = EXTRACTION_SCHEMA_VERSION


_SEVERITY_WORDS = {
    "critical": ["critical", "emergency", "severe", "burst", "flood", "total loss"],
    "high": ["urgent", "high", "major", "failure", "broken", "leak", "dead"],
    "medium": ["moderate", "medium", "concern", "stress", "wilting"],
    "low": ["minor", "low", "slight"],
}

_EVENT_WORDS = {
    "irrigation_event": ["irrigat", "watered", "ran the pump", "valve", "runtime"],
    "issue": ["problem", "issue", "broken", "leak", "failure", "clogged"],
    "pest_disease": ["pest", "mite", "aphid", "mildew", "fungus", "disease", "blight"],
    "meter_reading": ["meter", "reading", "gauge"],
    "equipment": ["pump", "filter", "tractor", "sensor", "controller"],
    "compliance_note": ["compliance", "report", "regulation", "permit"],
}

_NUM = r"(\d+(?:\.\d+)?)"


def _classify_event(text: str) -> EventType:
    low = text.lower()
    for event, words in _EVENT_WORDS.items():
        if any(word in low for word in words):
            return event  # type: ignore[return-value]
    return "observation"


def _classify_severity(text: str) -> Severity:
    low = text.lower()
    for severity, words in _SEVERITY_WORDS.items():
        if any(word in low for word in words):
            return severity  # type: ignore[return-value]
    return "info"


def _find_measurement(text: str, unit_pattern: str, label: str, unit: str) -> Optional[float]:
    match = re.search(_NUM + r"\s*" + unit_pattern, text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def deterministic_extract(
    text: str,
    *,
    field_hint: str | None = None,
    block_hint: str | None = None,
    crop_hint: str | None = None,
    occurred_at: datetime | None = None,
) -> FieldObservationExtraction:
    """Rule-based extraction that never invents values it cannot see."""
    text = (text or "").strip()
    uncertain: list[str] = []

    event_type = _classify_event(text)
    severity = _classify_severity(text)

    duration = _find_measurement(text, r"(?:minutes|mins|min)\b", "duration", "minutes")
    gallons = _find_measurement(text, r"(?:gallons|gal)\b", "applied_water", "gallons")
    flow = _find_measurement(text, r"(?:gpm|gallons per minute)\b", "flow_rate", "gpm")

    measurements: list[Measurement] = []
    if duration is not None:
        measurements.append(Measurement(label="irrigation_duration", value=duration, unit="minutes"))
    if gallons is not None:
        measurements.append(Measurement(label="applied_water", value=gallons, unit="gallons"))
    if flow is not None:
        measurements.append(Measurement(label="flow_rate", value=flow, unit="gpm"))

    # Field/block come from explicit hints (structured composer fields) rather
    # than free-text guessing, unless the text plainly names a block.
    field_candidate = field_hint
    block_candidate = block_hint
    if not block_candidate:
        block_match = re.search(r"block\s+([a-z0-9\-]+)", text, re.IGNORECASE)
        if block_match:
            block_candidate = f"Block {block_match.group(1).upper()}"
            uncertain.append("block_candidate")
    if not field_candidate:
        uncertain.append("field_candidate")

    issue = None
    if event_type in {"issue", "pest_disease", "equipment"}:
        issue = text[:240] if text else None

    # Confidence reflects how much we could ground, not model certainty.
    grounded = sum(
        [
            bool(field_candidate),
            bool(measurements),
            event_type != "observation",
            severity != "info",
        ]
    )
    confidence = round(min(0.35 + 0.15 * grounded, 0.9), 2) if text else 0.0

    recommended = None
    evidence_reqs: list[str] = []
    if severity in {"high", "critical"}:
        recommended = "Dispatch a field check and confirm the issue with a follow-up photo."
        evidence_reqs.append("photo")
    if event_type == "irrigation_event" and gallons is None and duration is None:
        evidence_reqs.append("meter_reading")
        uncertain.append("applied_water_gallons")

    summary = text[:280] if text else ""

    return FieldObservationExtraction(
        event_type=event_type,
        field_candidate=field_candidate,
        block_candidate=block_candidate,
        crop=crop_hint,
        issue=issue,
        severity=severity,
        measurements=measurements,
        irrigation_duration_minutes=duration,
        applied_water_gallons=gallons,
        flow_rate_gpm=flow,
        occurrence_time=occurred_at,
        recommended_follow_up=recommended,
        evidence_requirements=evidence_reqs,
        summary=summary,
        confidence=confidence,
        uncertain_fields=sorted(set(uncertain)),
    )


def extract_observation(
    text: str,
    *,
    field_hint: str | None = None,
    block_hint: str | None = None,
    crop_hint: str | None = None,
    event_type_hint: str | None = None,
    occurred_at: datetime | None = None,
) -> FieldObservationExtraction:
    """Public entrypoint.

    Currently backed by the deterministic extractor. A model-routed extractor
    (validated against :class:`FieldObservationExtraction`) can be layered in
    behind this function without changing callers or routes.
    """
    result = deterministic_extract(
        text,
        field_hint=field_hint,
        block_hint=block_hint,
        crop_hint=crop_hint,
        occurred_at=occurred_at,
    )
    if event_type_hint:
        # Explicit composer selection wins over inferred classification.
        try:
            result = result.model_copy(update={"event_type": event_type_hint})
        except Exception:
            pass
    return result
