"""Schema-constrained structured extraction for field observations.

Two extractors behind one strict Pydantic schema:

* a deterministic rule extractor (always available, fully offline);
* a model-routed extractor through the existing :class:`ModelRouter`, with
  hard grounding validation — a model value that is not literally supported
  by the source text or the authorized workspace vocabulary is discarded and
  recorded as uncertain, never persisted as fact.

Model-provider logic stays out of routes, the fallback is truthful
(``method`` provenance says exactly which path produced the result), and
nothing ever fabricates a field, block, measurement or timestamp.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

# Version the schema + prompts so provenance is auditable.
EXTRACTION_SCHEMA_VERSION = "field-observation-extraction/1.1.0"
EXTRACTION_METHOD_DETERMINISTIC = "deterministic-v1"
EXTRACTION_METHOD_MODEL = "model-routed-v1"
EXTRACTION_PROMPT_VERSION = "field-extraction-prompt/1"

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
    prompt_version: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    fallback_reason: Optional[str] = None


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


# --------------------------------------------------------------------------- #
# Model-routed extraction (schema-constrained, grounded, truthful fallback)
# --------------------------------------------------------------------------- #

_ALLOWED_EVENT_TYPES = {
    "observation", "irrigation_event", "issue", "meter_reading",
    "pest_disease", "equipment", "compliance_note", "operator_note",
}
_ALLOWED_SEVERITIES = {"info", "low", "medium", "high", "critical"}


def _run_coroutine(coro):
    """Run a coroutine from sync code, even inside a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result: dict = {}

    def _target() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001 - surfaced to caller
            result["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _numbers_in(text: str) -> set[str]:
    return {match.replace(",", "") for match in re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")}


def _normalize_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _ground_model_output(
    raw: dict,
    text: str,
    *,
    field_hint: str | None,
    block_hint: str | None,
    crop_hint: str | None,
    occurred_at: datetime | None,
    workspace_fields: list[str] | None,
    workspace_blocks: list[str] | None,
    workspace_crops: list[str] | None,
) -> FieldObservationExtraction:
    """Validate + ground a model response. Anything the source text or the
    authorized workspace vocabulary cannot support is discarded and recorded
    as uncertain — the model can propose, never assert."""
    uncertain: set[str] = set()
    source_numbers = _numbers_in(text)

    def grounded_number(value) -> Optional[float]:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        token = ("%g" % number)
        if token in source_numbers or str(int(number)) in source_numbers:
            return number
        return None  # not literally present in the note: rejected

    event_type = str(raw.get("event_type") or "observation").strip().lower()
    if event_type not in _ALLOWED_EVENT_TYPES:
        event_type = "observation"
        uncertain.add("event_type")
    severity = str(raw.get("severity") or "info").strip().lower()
    if severity not in _ALLOWED_SEVERITIES:
        severity = "info"
        uncertain.add("severity")

    def match_vocabulary(candidate, vocabulary, hint, label):
        if hint:
            return hint  # explicit composer selection is authoritative
        value = str(candidate or "").strip() or None
        if not value:
            uncertain.add(label)
            return None
        normalized = _normalize_name(value)
        for known in vocabulary or []:
            if _normalize_name(known) == normalized:
                return known  # authorized workspace spelling wins
        if _normalize_name(value) and _normalize_name(value) in _normalize_name(text):
            uncertain.add(label)  # present in the note but not an authorized name
            return value
        uncertain.add(label)
        return None  # not in the note, not authorized: rejected

    field_candidate = match_vocabulary(raw.get("field_candidate"), workspace_fields, field_hint, "field_candidate")
    block_candidate = match_vocabulary(raw.get("block_candidate"), workspace_blocks, block_hint, "block_candidate")
    crop = match_vocabulary(raw.get("crop"), workspace_crops, crop_hint, "crop")

    measurements: list[Measurement] = []
    for item in (raw.get("measurements") or [])[:20]:
        if not isinstance(item, dict):
            continue
        value = grounded_number(item.get("value"))
        label = str(item.get("label") or "").strip()[:80]
        unit = str(item.get("unit") or "").strip()[:40]
        if value is None or not label or not unit:
            if label:
                uncertain.add(f"measurement:{label}")
            continue
        measurements.append(Measurement(label=label, value=value, unit=unit))

    duration = grounded_number(raw.get("irrigation_duration_minutes"))
    gallons = grounded_number(raw.get("applied_water_gallons"))
    flow = grounded_number(raw.get("flow_rate_gpm"))
    for name, value in (("irrigation_duration_minutes", raw.get("irrigation_duration_minutes")),
                        ("applied_water_gallons", raw.get("applied_water_gallons")),
                        ("flow_rate_gpm", raw.get("flow_rate_gpm"))):
        if value is not None and grounded_number(value) is None:
            uncertain.add(name)

    # Timestamps are never taken from the model: only the composer-supplied
    # occurrence time (or nothing) is persisted.
    if raw.get("occurrence_time") and occurred_at is None:
        uncertain.add("occurrence_time")

    people = [str(p).strip()[:80] for p in (raw.get("people") or [])[:10]
              if str(p).strip() and _normalize_name(str(p)) in _normalize_name(text)]
    equipment = [str(e).strip()[:80] for e in (raw.get("equipment") or [])[:10] if str(e).strip()]

    issue = str(raw.get("issue") or "").strip()[:240] or None
    recommended = str(raw.get("recommended_follow_up") or "").strip()[:500] or None
    evidence_requirements = [str(e).strip()[:60] for e in (raw.get("evidence_requirements") or [])[:10] if str(e).strip()]
    summary = str(raw.get("summary") or "").strip()[:280] or (text or "")[:280]

    try:
        confidence = max(0.0, min(float(raw.get("confidence") or 0.0), 1.0))
    except (TypeError, ValueError):
        confidence = 0.0
    for entry in raw.get("uncertain_fields") or []:
        uncertain.add(str(entry)[:60])
    if uncertain:
        confidence = min(confidence, 0.85)

    return FieldObservationExtraction(
        event_type=event_type,  # type: ignore[arg-type]
        field_candidate=field_candidate,
        block_candidate=block_candidate,
        crop=crop,
        issue=issue,
        severity=severity,  # type: ignore[arg-type]
        measurements=measurements,
        irrigation_duration_minutes=duration,
        applied_water_gallons=gallons,
        flow_rate_gpm=flow,
        equipment=equipment,
        people=people,
        occurrence_time=occurred_at,
        recommended_follow_up=recommended,
        evidence_requirements=evidence_requirements,
        summary=summary,
        confidence=confidence,
        uncertain_fields=sorted(uncertain),
        method=EXTRACTION_METHOD_MODEL,
        prompt_version=EXTRACTION_PROMPT_VERSION,
    )


def _model_extract(
    text: str,
    *,
    field_hint: str | None,
    block_hint: str | None,
    crop_hint: str | None,
    occurred_at: datetime | None,
    workspace_fields: list[str] | None,
    workspace_blocks: list[str] | None,
    workspace_crops: list[str] | None,
) -> FieldObservationExtraction | None:
    """Schema-constrained extraction through the existing model router.

    Returns None (with the reason logged) when the router is unconfigured or
    the response cannot be validated — the caller falls back truthfully.
    """
    from app.services.model_router import ModelRouter

    router = ModelRouter()
    if router.mode() == "offline":
        return None
    vocabulary = {
        "fields": (workspace_fields or [])[:50],
        "blocks": (workspace_blocks or [])[:50],
        "crops": (workspace_crops or [])[:25],
    }
    system = (
        "You extract structured agricultural field observations. Reply with ONLY a JSON object "
        "matching this schema: {event_type: one of observation|irrigation_event|issue|meter_reading|"
        "pest_disease|equipment|compliance_note|operator_note, field_candidate: string|null, "
        "block_candidate: string|null, crop: string|null, issue: string|null, severity: one of "
        "info|low|medium|high|critical, measurements: [{label, value, unit}], "
        "irrigation_duration_minutes: number|null, applied_water_gallons: number|null, "
        "flow_rate_gpm: number|null, equipment: [string], people: [string], "
        "recommended_follow_up: string|null, evidence_requirements: [string], summary: string, "
        "confidence: number 0..1, uncertain_fields: [string]}. "
        "The observation may be in any language; keep summary in the source language. "
        "NEVER invent numbers, names, fields, times or measurements that are not explicitly in the text. "
        "Prefer field/block/crop names from the authorized vocabulary. "
        "List anything you are unsure about in uncertain_fields."
    )
    user = json.dumps({
        "observation_text": (text or "")[:8000],
        "authorized_vocabulary": vocabulary,
        "hints": {"field": field_hint, "block": block_hint, "crop": crop_hint},
    }, ensure_ascii=False)
    try:
        result, selection = _run_coroutine(router.run(
            task="field_observation_extraction",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=1200,
            timeout_seconds=45,
        ))
    except Exception as exc:  # noqa: BLE001 - fall back truthfully
        logger.warning("model extraction transport failure: %s", exc.__class__.__name__)
        return None
    if getattr(result, "status", "") != "ok" or not (result.content or "").strip():
        return None
    from app.services.ai_gateway import parse_model_json

    try:
        raw = parse_model_json(result.content)
    except Exception:  # noqa: BLE001
        logger.warning("model extraction returned unparseable JSON")
        return None
    try:
        grounded = _ground_model_output(
            raw, text,
            field_hint=field_hint, block_hint=block_hint, crop_hint=crop_hint,
            occurred_at=occurred_at,
            workspace_fields=workspace_fields, workspace_blocks=workspace_blocks,
            workspace_crops=workspace_crops,
        )
    except ValidationError:
        logger.warning("model extraction failed schema validation")
        return None
    return grounded.model_copy(update={
        "provider": getattr(result, "provider", None),
        "model": getattr(result, "model", None) or getattr(selection, "model", None),
    })


def extract_observation(
    text: str,
    *,
    field_hint: str | None = None,
    block_hint: str | None = None,
    crop_hint: str | None = None,
    event_type_hint: str | None = None,
    occurred_at: datetime | None = None,
    workspace_fields: list[str] | None = None,
    workspace_blocks: list[str] | None = None,
    workspace_crops: list[str] | None = None,
    allow_model: bool = True,
) -> FieldObservationExtraction:
    """Public entrypoint: model-routed when configured, deterministic fallback.

    ``FIELD_EXTRACTION_MODE``: ``auto`` (model when the router is live, else
    deterministic), ``model`` (model only; deterministic fallback is labeled),
    ``deterministic`` (never call a model).
    """
    from app.core.config import settings

    mode = str(getattr(settings, "FIELD_EXTRACTION_MODE", "auto") or "auto").strip().lower()
    result: FieldObservationExtraction | None = None
    fallback_reason: str | None = None
    if not allow_model:
        mode = "deterministic"
        fallback_reason = "model_extraction_not_entitled"
    if mode in {"auto", "model"} and (text or "").strip():
        result = _model_extract(
            text,
            field_hint=field_hint, block_hint=block_hint, crop_hint=crop_hint,
            occurred_at=occurred_at,
            workspace_fields=workspace_fields, workspace_blocks=workspace_blocks,
            workspace_crops=workspace_crops,
        )
        if result is None and mode in {"auto", "model"}:
            fallback_reason = "model_unavailable_or_invalid"
    if result is None:
        result = deterministic_extract(
            text,
            field_hint=field_hint,
            block_hint=block_hint,
            crop_hint=crop_hint,
            occurred_at=occurred_at,
        )
        if fallback_reason:
            result = result.model_copy(update={"fallback_reason": fallback_reason})
    if event_type_hint:
        # Explicit composer selection wins over inferred classification.
        try:
            result = result.model_copy(update={"event_type": event_type_hint})
        except Exception:
            pass
    return result
